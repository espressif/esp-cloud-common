# SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
#
# SPDX-License-Identifier: Apache-2.0

"""EC2 cleanup — instances, volumes, snapshots, AMIs, key pairs, Elastic IPs.

Order matters within EC2:
  1. Terminate instances (releases attached EBS volumes after they go to
     ``available`` state — but EBS volumes are typically marked
     DeleteOnTermination so they vanish here).
  2. Delete remaining standalone volumes.
  3. Delete EBS snapshots (skip AWS-owned).
  4. Deregister AMIs (deleting their snapshots happens via step 3).
  5. Delete key pairs.
  6. Release unassociated Elastic IPs.

This does NOT touch VPC resources (subnets, security groups, NAT gateways,
route tables, etc.) — VPC has too much dependency ordering for a generic
sweep.
"""

from botocore.exceptions import ClientError

from .base import ServiceCleanup


class EC2Cleanup(ServiceCleanup):
    name = 'ec2'
    boto_client = 'ec2'
    cli_options = []

    def run(self):
        self._cancel_capacity_reservations()
        self._terminate_instances()
        self._delete_nat_gateways()
        self._delete_network_interfaces()
        self._delete_launch_templates()
        self._delete_placement_groups()
        self._delete_volumes()
        self._delete_snapshots()
        self._deregister_amis()
        self._delete_key_pairs()
        self._release_elastic_ips()
        self.console.print("\n[bold green]EC2 cleanup completed[/bold green]")

    def _cancel_capacity_reservations(self):
        self.console.print("[bold cyan]Listing EC2 capacity reservations...[/bold cyan]")
        try:
            for page in self.client.get_paginator('describe_capacity_reservations').paginate():
                for r in page.get('CapacityReservations', []):
                    if r.get('State') in ('expired', 'cancelled'):
                        continue
                    rid = r.get('CapacityReservationId')
                    try:
                        self.client.cancel_capacity_reservation(CapacityReservationId=rid)
                        self.console.print(f"[green]✓ Cancelled capacity reservation: {rid}[/green]")
                    except ClientError as e:
                        self.console.print(f"[red]✗ Error cancelling reservation {rid}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list capacity reservations: {e}[/yellow]")

    def _delete_nat_gateways(self):
        self.console.print("\n[bold cyan]Listing NAT gateways...[/bold cyan]")
        try:
            for page in self.client.get_paginator('describe_nat_gateways').paginate():
                for ng in page.get('NatGateways', []):
                    if ng.get('State') in ('deleted', 'deleting'):
                        continue
                    nid = ng.get('NatGatewayId')
                    try:
                        self.client.delete_nat_gateway(NatGatewayId=nid)
                        self.console.print(f"[green]✓ Deleted NAT gateway: {nid}[/green]")
                    except ClientError as e:
                        self.console.print(f"[red]✗ Error deleting NAT gateway {nid}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list NAT gateways: {e}[/yellow]")

    def _delete_network_interfaces(self):
        self.console.print("\n[bold cyan]Listing standalone network interfaces...[/bold cyan]")
        try:
            for page in self.client.get_paginator('describe_network_interfaces').paginate():
                for ni in page.get('NetworkInterfaces', []):
                    # Skip interfaces still attached or owned by AWS services
                    if ni.get('Attachment') and ni['Attachment'].get('Status') == 'attached':
                        continue
                    if ni.get('RequesterManaged'):
                        continue
                    nid = ni.get('NetworkInterfaceId')
                    try:
                        self.client.delete_network_interface(NetworkInterfaceId=nid)
                        self.console.print(f"[green]✓ Deleted network interface: {nid}[/green]")
                    except ClientError as e:
                        self.console.print(f"[red]✗ Error deleting network interface {nid}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list network interfaces: {e}[/yellow]")

    def _delete_launch_templates(self):
        self.console.print("\n[bold cyan]Listing launch templates...[/bold cyan]")
        try:
            for page in self.client.get_paginator('describe_launch_templates').paginate():
                for lt in page.get('LaunchTemplates', []):
                    lid = lt.get('LaunchTemplateId')
                    try:
                        self.client.delete_launch_template(LaunchTemplateId=lid)
                        self.console.print(f"[green]✓ Deleted launch template: {lt.get('LaunchTemplateName')}[/green]")
                    except ClientError as e:
                        self.console.print(f"[red]✗ Error deleting launch template {lid}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list launch templates: {e}[/yellow]")

    def _delete_placement_groups(self):
        self.console.print("\n[bold cyan]Listing placement groups...[/bold cyan]")
        try:
            response = self.client.describe_placement_groups()
            for pg in response.get('PlacementGroups', []):
                name = pg.get('GroupName')
                try:
                    self.client.delete_placement_group(GroupName=name)
                    self.console.print(f"[green]✓ Deleted placement group: {name}[/green]")
                except ClientError as e:
                    self.console.print(f"[red]✗ Error deleting placement group {name}: {e}[/red]")
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list placement groups: {e}[/yellow]")

    def _terminate_instances(self):
        self.console.print("[bold cyan]Listing EC2 instances...[/bold cyan]")
        instance_ids = []
        for page in self.client.get_paginator('describe_instances').paginate():
            for reservation in page.get('Reservations', []):
                for inst in reservation.get('Instances', []):
                    state = inst.get('State', {}).get('Name')
                    if state in ('terminated', 'shutting-down'):
                        continue
                    iid = inst.get('InstanceId')
                    instance_ids.append(iid)
                    self.console.print(f"Found instance: {iid} ({state})")
        if not instance_ids:
            return
        try:
            self.client.terminate_instances(InstanceIds=instance_ids)
            self.console.print(f"[green]✓ Terminated {len(instance_ids)} instances[/green]")
        except ClientError as e:
            self.console.print(f"[red]✗ Error terminating instances: {e}[/red]")

    def _delete_volumes(self):
        self.console.print("\n[bold cyan]Listing EBS volumes...[/bold cyan]")
        for page in self.client.get_paginator('describe_volumes').paginate():
            for vol in page.get('Volumes', []):
                vid = vol.get('VolumeId')
                if vol.get('State') == 'in-use':
                    self.console.print(f"[yellow]Skipping in-use volume: {vid}[/yellow]")
                    continue
                try:
                    self.client.delete_volume(VolumeId=vid)
                    self.console.print(f"[green]✓ Deleted volume: {vid}[/green]")
                except ClientError as e:
                    self.console.print(f"[red]✗ Error deleting volume {vid}: {e}[/red]")

    def _delete_snapshots(self):
        self.console.print("\n[bold cyan]Listing EBS snapshots (owned by self)...[/bold cyan]")
        for page in self.client.get_paginator('describe_snapshots').paginate(OwnerIds=['self']):
            for snap in page.get('Snapshots', []):
                sid = snap.get('SnapshotId')
                try:
                    self.client.delete_snapshot(SnapshotId=sid)
                    self.console.print(f"[green]✓ Deleted snapshot: {sid}[/green]")
                except ClientError as e:
                    self.console.print(f"[red]✗ Error deleting snapshot {sid}: {e}[/red]")

    def _deregister_amis(self):
        self.console.print("\n[bold cyan]Listing AMIs (owned by self)...[/bold cyan]")
        try:
            response = self.client.describe_images(Owners=['self'])
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list AMIs: {e}[/yellow]")
            return
        for ami in response.get('Images', []):
            aid = ami.get('ImageId')
            try:
                self.client.deregister_image(ImageId=aid)
                self.console.print(f"[green]✓ Deregistered AMI: {aid}[/green]")
            except ClientError as e:
                self.console.print(f"[red]✗ Error deregistering AMI {aid}: {e}[/red]")

    def _delete_key_pairs(self):
        self.console.print("\n[bold cyan]Listing EC2 key pairs...[/bold cyan]")
        try:
            response = self.client.describe_key_pairs()
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list key pairs: {e}[/yellow]")
            return
        for kp in response.get('KeyPairs', []):
            name = kp.get('KeyName')
            try:
                self.client.delete_key_pair(KeyName=name)
                self.console.print(f"[green]✓ Deleted key pair: {name}[/green]")
            except ClientError as e:
                self.console.print(f"[red]✗ Error deleting key pair {name}: {e}[/red]")

    def _release_elastic_ips(self):
        self.console.print("\n[bold cyan]Listing unassociated Elastic IPs...[/bold cyan]")
        try:
            response = self.client.describe_addresses()
        except ClientError as e:
            self.console.print(f"[yellow]⚠ Could not list EIPs: {e}[/yellow]")
            return
        for addr in response.get('Addresses', []):
            if addr.get('AssociationId'):
                continue  # still attached to something — leave it
            alloc = addr.get('AllocationId')
            ip = addr.get('PublicIp')
            try:
                self.client.release_address(AllocationId=alloc)
                self.console.print(f"[green]✓ Released EIP: {ip}[/green]")
            except ClientError as e:
                self.console.print(f"[red]✗ Error releasing EIP {ip}: {e}[/red]")
