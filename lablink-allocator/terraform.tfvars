# DNS configuration for the allocator
# This file contains Talmo Lab's specific DNS setup as an example
# For template users: modify or leave empty based on your DNS configuration in config.yaml
#
# To disable DNS: set dns_name = ""
# To enable DNS: set dns_name to your desired domain (e.g., "example.com")
#
# Note: The actual FQDN will be auto-generated based on environment:
#   - prod: lablink.sleap.ai
#   - test: test.lablink.sleap.ai
#   - dev: dev.lablink.sleap.ai
#
# This can be configured in lablink-allocator-service/conf/config.yaml

dns_name = "sleap.ai"
