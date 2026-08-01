# Docker file to be used for CI dependencies
# docker build . -> Returns an image ID
# docker run <image-id>

# For Go:1.20.2
FROM golangci/golangci-lint:v1.52-alpine

# Verify go and golangci-lint
RUN go version && golangci-lint version

RUN apk add curl && \
    curl -o /bin/nancy -L https://github.com/sonatype-nexus-community/nancy/releases/download/v1.0.42/nancy-v1.0.42-linux-amd64 && \
    chmod +x /bin/nancy && nancy --version

# Install tools to convert go coverage report to cobertura format.
# https://docs.gitlab.com/ee/user/project/merge_requests/test_coverage_visualization.html
# Commands to create a image
# docker login <registry_url>
# docker build -t <registry_url>/rbacvalidator:v18May2023 .
# To verify the image
# docker run <registry_url>/rbacvalidator:v18May2023 golangci-lint -v
# To change the tag of the image
# docker tag c967698c <registry_url>/rbacvalidator:v18May2023
# To keep running the container
# docker run -d <registry_url>/rbacvalidator:v18May2023 tail -f /dev/null
# docker ps
# To get shell access to the container
# docker exec -it 50683ec32df5 /bin/sh
# To push the image
# docker push <registry_url>/rbacvalidator:v18May2023
