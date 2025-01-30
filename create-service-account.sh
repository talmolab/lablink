# Project ID as an argument
PROJECT_ID=$1

# Create the service account
gcloud iam service-accounts create service-account-admin \
    --description="Service account to create and manage other service accounts" \
    --display-name="Service Account Admin" \
    --project="${PROJECT_ID}"

# Grant roles to allow service account management
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
    --member="serviceAccount:service-account-admin@${PROJECT_ID}.iam.gserviceaccount.com" \
    --role="roles/iam.serviceAccountAdmin"

# Grant roles to allow assignment of roles to other service accounts
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
    --member="serviceAccount:service-account-admin@${PROJECT_ID}.iam.gserviceaccount.com" \
    --role="roles/iam.roleAdmin"

# Generate a key for the service account
gcloud iam service-accounts keys create terraform/service-account-admin-key.json \
    --iam-account="service-account-admin@${PROJECT_ID}.iam.gserviceaccount.com" \
    --project="${PROJECT_ID}"