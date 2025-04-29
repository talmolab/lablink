#!/bin/bash

echo "Running subscribe script..."
# Activate the conda environment and run the subscribe script
/home/client/miniforge3/bin/conda run -n base subscribe db.host=$DB_HOST