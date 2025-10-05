# Frequently Asked Questions (FAQ)

Common questions and answers about LabLink.

## General

### What is LabLink?

LabLink is a dynamic VM allocation and management system designed for computational research. It automates the deployment and management of cloud-based VMs for running research software like SLEAP or custom tools.

### Who is LabLink for?

- Research labs needing on-demand GPU compute resources
- Scientists running batch computational workloads
- Teams training machine learning models on cloud infrastructure
- Anyone needing automated VM management for containerized software

### What cloud providers does LabLink support?

Currently, LabLink supports **AWS (Amazon Web Services)** only. The architecture uses AWS-specific services (EC2, S3, IAM).

### Is LabLink free?

LabLink itself is open-source and free. However, you'll pay for AWS resources you use (EC2 instances, S3 storage, etc.). See [Cost Estimation](cost-estimation.md).

## Installation & Setup

### Do I need an AWS account?

Yes. LabLink deploys to AWS and requires an AWS account with permissions to create EC2 instances, security groups, and other resources.

### How long does setup take?

- **Initial AWS setup**: 1-2 hours (first time)
- **Local testing**: 5-10 minutes
- **First deployment**: 10-15 minutes

### Can I run LabLink locally without AWS?

You can run the allocator locally with Docker for testing, but creating client VMs requires AWS.

## Configuration

### How do I change the GPU type?

Edit the allocator configuration:

```yaml
# lablink-infrastructure/config/config.yaml
machine:
  machine_type: "g5.xlarge"  # Change to desired instance type
```

See [Configuration → Machine Type Options](configuration.md#machine-type-options) for available types.

### How do I use my own research software?

1. Create a Docker image with your software
2. Push to a container registry (e.g., ghcr.io)
3. Update configuration with your image URL
4. Optionally specify your code repository

See [Adapting LabLink](adapting.md) for detailed guide.

### Can I use a different AWS region?

Yes. Update the region in configuration:

```yaml
app:
  region: "us-east-1"  # Change to your preferred region
```

**Important**: AMI IDs are region-specific. You'll need to find the appropriate AMI for your region.

### How do I change default passwords?

**Critical for production!**

```yaml
# In config.yaml
app:
  admin_user: "admin"
  admin_password: "YOUR_SECURE_PASSWORD"

db:
  password: "YOUR_SECURE_DB_PASSWORD"
```

Or use environment variables. See [Security → Change Default Passwords](security.md#change-default-passwords).

### Why does my browser say "Not Secure"?

You're using staging mode (`ssl.staging: true`), which serves HTTP only (no encryption). This is expected for testing.

To get a secure HTTPS connection with browser padlock, set `ssl.staging: false` in your configuration and redeploy.

See [Configuration → SSL Options](configuration.md#ssltls-options-ssl).

### Why can't I access the allocator in my browser?

If your browser cannot connect to `http://your-domain.com`:

1. Make sure you explicitly type `http://` (not `https://`)
2. Clear your browser's HSTS cache (see [Troubleshooting → Browser HSTS](troubleshooting.md#browser-cannot-access-http-staging-mode))
3. Try incognito/private browsing mode
4. Try accessing via IP address: `http://<allocator-ip>`

### Should I use staging or production mode?

**Use staging mode (`ssl.staging: true`) for:**

- Initial testing and development
- Frequent deployments (unlimited)
- Testing infrastructure changes
- CI/CD automated tests

**Use production mode (`ssl.staging: false`) for:**

- Production deployments
- Internet-accessible allocators
- Handling sensitive data
- Long-running deployments

**Key difference:** Staging = HTTP only (fast, unlimited, no encryption). Production = HTTPS with trusted certificates (secure, rate limited).

See [Configuration → Staging vs Production](configuration.md#staging-vs-production-mode).

### How many times can I deploy with staging mode?

Unlimited. Staging mode uses HTTP only, so there are no Let's Encrypt rate limits.

With production mode, you're limited to 5 duplicate certificates per week.

### Can I switch from staging to production mode?

Yes. Change the configuration and redeploy:

```yaml
ssl:
  staging: false
```

Then run:
```bash
terraform apply
```

The allocator will obtain a trusted Let's Encrypt certificate and start serving HTTPS. You may need to clear your browser's HSTS cache.

## Deployment

### What's the difference between dev, test, and prod environments?

| Environment | Purpose | Image Tags | Terraform State |
|-------------|---------|------------|-----------------|
| **dev** | Local development | `-test` | Local file |
| **test** | Staging/pre-prod | `-test` | S3 bucket |
| **prod** | Production | Pinned versions | S3 bucket |

See [Deployment → Environment-Specific Configurations](deployment.md#environment-specific-configurations).

### How do I deploy to production?

1. Navigate to **Actions** tab in GitHub
2. Select "Terraform Deploy" workflow
3. Click "Run workflow"
4. Select `prod` environment
5. Enter specific image tag (e.g., `v1.0.0`)
6. Click "Run workflow"

**Never use `:latest` in production!**

### Can I deploy without GitHub Actions?

Yes, using Terraform CLI:

```bash
cd lablink-allocator
terraform init
terraform apply -var="resource_suffix=prod" -var="allocator_image_tag=v1.0.0"
```

See [Deployment → Method 2: Manual Terraform](deployment.md#method-2-manual-terraform-deployment).

### How do I update an existing deployment?

```bash
# Pull latest code
git pull

# Re-apply Terraform with new image tag
terraform apply -var="resource_suffix=prod" -var="allocator_image_tag=v1.1.0"
```

This will replace the EC2 instance with the new image.

## Operations

### How do I create client VMs?

**Via Web UI**:
1. Navigate to allocator web interface
2. Login with admin credentials
3. Go to **Admin → Create Instances**
4. Enter number of VMs
5. Submit

**Via API**:
```bash
curl -X POST http://<allocator-ip>:80/admin/create \
  -u admin:password \
  -d "instance_count=5"
```

### How do I check VM status?

**Via Web UI**:
- Navigate to **Admin → View Instances**

**Via Database**:
```bash
ssh -i ~/lablink-key.pem ubuntu@<allocator-ip>
sudo docker exec <container-id> psql -U lablink -d lablink_db -c "SELECT hostname, status, email FROM vms;"
```

### How do I destroy a deployment?

**Via GitHub Actions**:
1. Actions → "Allocator Master Destroy"
2. Run workflow
3. Select environment

**Via Terraform CLI**:
```bash
terraform destroy -var="resource_suffix=dev"
```

### What happens if I destroy the allocator?

- Allocator EC2 instance terminated
- Database data lost (unless backed up)
- Client VMs remain running (must be destroyed separately)

**Always backup database before destroying!**

## Troubleshooting

### PostgreSQL won't start after deployment

**Known issue**. Solution:

```bash
ssh -i ~/lablink-key.pem ubuntu@<allocator-ip>
sudo docker exec -it <container-id> bash
/etc/init.d/postgresql restart
```

See [Troubleshooting → PostgreSQL Issues](troubleshooting.md#postgresql-issues).

### I can't SSH into the instance

Check:
1. Key permissions: `chmod 600 ~/lablink-key.pem`
2. Security group allows port 22
3. Using correct IP address
4. Using correct user (`ubuntu`)

See [Troubleshooting → SSH Access Issues](troubleshooting.md#ssh-access-issues).

### Client VMs aren't being created

Check:
1. AWS credentials configured in allocator
2. Allocator container logs for errors
3. IAM permissions for EC2 operations

See [Troubleshooting → VM Spawning Issues](troubleshooting.md#vm-spawning-issues).

### I'm getting billed unexpectedly

- Check for running EC2 instances you forgot to terminate
- Set up billing alerts (see [AWS Setup → Billing Alerts](aws-setup.md#step-9-billing-alerts))
- Review [Cost Estimation](cost-estimation.md) guide

## Costs

### How much does LabLink cost to run?

**AWS infrastructure**:
- S3 bucket: ~$0.05/month
- Elastic IPs: Free while associated

**Running costs** (per hour):
- Allocator (t2.micro): $0.0116/hour (~$8.50/month if running 24/7)
- Client VM (g4dn.xlarge): $0.526/hour

See [Cost Estimation](cost-estimation.md) for detailed breakdown.

### How can I reduce costs?

1. **Terminate VMs when not in use**
2. **Use Spot Instances** for client VMs (up to 90% savings)
3. **Use smaller instance types** for testing
4. **Set up billing alerts** to monitor spending
5. **Use Reserved Instances** for long-running allocators (up to 75% savings)

### Do I get charged for stopped instances?

- **EC2 instances**: No compute charges, but EBS storage charges apply
- **Elastic IPs**: Free while associated, $0.005/hour if unassociated

**Best practice**: Terminate (not stop) instances when done.

## Advanced

### Can I use a custom AMI?

Yes. Create an AMI with your software pre-installed:

```bash
# Create AMI from running instance
aws ec2 create-image --instance-id i-xxxxx --name "my-custom-ami"

# Use in configuration
machine:
  ami_id: "ami-your-custom-ami-id"
```

See [Adapting LabLink → Custom AMI](adapting.md#custom-ami).

### Can I use RDS instead of PostgreSQL in Docker?

Yes, for production. See [Database → Migrating to RDS](database.md#migrating-to-rds-production).

**Benefits**:
- Automated backups
- High availability
- Managed updates

### Can I use LabLink with multiple AWS accounts?

Yes. Deploy separate instances with different AWS credentials/roles for each account.

### Can I add my own API endpoints?

Yes. Edit the allocator service in `packages/allocator/src/lablink_allocator/main.py`:

```python
@app.route('/my-custom-endpoint', methods=['POST'])
def my_custom_endpoint():
    # Your code here
    return jsonify({'status': 'success'})
```

Rebuild the Docker image and redeploy.

### How do I enable HTTPS?

1. Get SSL certificate (e.g., Let's Encrypt)
2. Configure nginx or use AWS Application Load Balancer
3. Update security groups to allow port 443

See [Security → Encryption in Transit](security.md#encryption-in-transit).

## Security

### Is it safe to use default passwords?

**No!** Change them immediately for any non-local deployment.

See [Security → Change Default Passwords](security.md#change-default-passwords).

### How are AWS credentials stored?

For GitHub Actions: **OIDC** (no stored credentials)

For local: AWS credentials file or environment variables

**Never commit credentials to version control!**

### How are SSH keys managed?

- Terraform generates unique keys per environment
- Keys stored in Terraform state
- GitHub Actions exposes keys as temporary artifacts (1 day expiration)
- Rotate keys by destroying and recreating infrastructure

See [SSH Access → Key Management](ssh-access.md#ssh-key-management).

## Contributing

### Can I contribute to LabLink?

Yes! LabLink is open-source. Contributions welcome:

1. Fork repository
2. Create feature branch
3. Make changes
4. Add tests
5. Submit pull request

### How do I report bugs?

Open an issue on [GitHub](https://github.com/talmolab/lablink/issues) with:
- Description of the bug
- Steps to reproduce
- Expected vs actual behavior
- Logs/error messages
- Environment details

### Where can I ask questions?

- **GitHub Issues**: For bugs and feature requests
- **GitHub Discussions**: For questions and general discussion

## Comparison

### How is LabLink different from AWS Batch?

| Feature | LabLink | AWS Batch |
|---------|---------|-----------|
| Setup complexity | Moderate | High |
| Custom software | Easy (Docker) | Easy (Docker) |
| GPU support | Yes | Yes |
| Cost | Pay for VMs | Pay for VMs + Batch overhead |
| Web UI | Included | Requires building |
| VM management | Automated | Automated |
| Learning curve | Moderate | Steep |

**LabLink advantage**: Simpler setup, included web UI, research-focused

### How is LabLink different from Kubernetes?

LabLink is simpler and more focused:

- **LabLink**: VM allocation for research workloads
- **Kubernetes**: General-purpose container orchestration

If you need simple VM management for research, use LabLink. If you need complex microservices orchestration, use Kubernetes.

## Still Have Questions?

- Check [Documentation](index.md)
- Search [GitHub Issues](https://github.com/talmolab/lablink/issues)
- Open new issue with your question