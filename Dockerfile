# Use a lightweight Python base image
FROM python:3.9-slim

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file
COPY app/requirements.txt requirements.txt

# Install Python dependencies
RUN pip install -r requirements.txt

# Copy the app code into the container
COPY ./app .

# Expose the port Flask will run on
EXPOSE 8080

# Command to run the Flask app
CMD ["python", "app.py"]
