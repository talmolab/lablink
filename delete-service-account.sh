#!/bin/bash

# Exit on any error
set -e

# Variables
PROJECT_ID="vmassign-dev"
SERVICE_ACCOUNT_NAME="service-account-admin"
SERVICE_ACCOUNT_EMAIL="${SERVICE_ACCOUNT_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

echo "Deleting IAM bindings for service account: $SERVICE_ACCOUNT_EMAIL"

gcloud projects get-iam-policy $PROJECT_ID \
  --flatten="bindings[].members" \
  --format="table(bindings.role)" \
  --filter="bindings.members:serviceAccount:$SERVICE_ACCOUNT_EMAIL"

# Get the IAM roles assigned to the service account
IAM_ROLES=$(gcloud projects get-iam-policy $PROJECT_ID \
  --flatten="bindings[].members" \
  --format="table(bindings.role)" \
  --filter="bindings.members:$SERVICE_ACCOUNT_EMAIL")

echo "IAM roles assigned to $SERVICE_ACCOUNT_EMAIL: $IAM_ROLES"

# Remove ROLE column header from the output
IAM_ROLES=$(echo "$IAM_ROLES" | sed '1d')


# Revoke IAM roles assigned to the service account
if [ -z "$IAM_ROLES" ]; then
    echo "No active IAM roles found for $SERVICE_ACCOUNT_EMAIL."
else
    # Remove IAM roles only for the active service account
    for ROLE in $IAM_ROLES; do
        echo "Removing IAM role: $ROLE"
        gcloud projects remove-iam-policy-binding $PROJECT_ID \
            --member="serviceAccount:$SERVICE_ACCOUNT_EMAIL" \
            --role="$ROLE"
    done
fi


# Delete the service account
echo "Deleting service account: $SERVICE_ACCOUNT_EMAIL"
gcloud iam service-accounts delete $SERVICE_ACCOUNT_EMAIL --quiet


# Check if the service account still exists before deleting
if gcloud iam service-accounts describe $SERVICE_ACCOUNT_EMAIL &>/dev/null; then
    echo "Deleting service account: $SERVICE_ACCOUNT_EMAIL"
    gcloud projects set-iam-policy $PROJECT_ID <(gcloud projects get-iam-policy $PROJECT_ID --format=json | jq 'del(.bindings[] | select(.members[] | contains("serviceAccount:'"$SERVICE_ACCOUNT_EMAIL"'")))')
else
    echo "Service account $SERVICE_ACCOUNT_EMAIL does not exist."
fi

# Delete the key file
echo "Deleting key file: terraform/service-account-admin-key.json"
rm -f terraform/service-account-admin-key.json

echo "Service account $SERVICE_ACCOUNT_EMAIL deleted successfully!"
