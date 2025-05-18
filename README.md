
# MP3 Converter Microservice

This document provides detailed guidance on setting up, deploying, and using the MP3 Converter Microservice application built with Python, Docker, and Kubernetes.

## Project Overview

The MP3 Converter Microservice is a cloud-native application that enables users to upload video files and convert them to MP3 audio format. The application consists of several microservices:

- **Gateway Service**: Entry point for the application, handles authentication and file operations
- **Auth Service**: Manages user authentication and authorization
- **Converter Service**: Processes video files and converts them to MP3 format
- **Notification Service**: Sends email notifications when conversion is complete
- **MongoDB**: Stores video files, MP3 files, and metadata

## Setup and Deployment

### Building and Pushing Docker Images

Each microservice requires its own Docker image:
```
bash
# Build Gateway service
docker build -t selcukakarin/gateway:latest . docker push selcukakarin/gateway:latest
# Build Auth service
docker build -t selcukakarin/auth:latest . docker push selcukakarin/auth:latest
# Build Converter service
docker build -t selcukakarin/converter:latest . docker push selcukakarin/converter:latest
# Build Notification service
docker build -t selcukakarin/notification:latest . docker push selcukakarin/notification:latest
``` 

These commands build Docker images for each service and push them to Docker Hub. The `docker tag` commands associate the local image ID with your repository name.

### Deploying to Kubernetes

Deploy all services to Kubernetes:
```
bash
# Delete existing deployments (if any)
kubectl delete -f ./manifests/
# Apply all manifests
kubectl apply -f ./manifests/
``` 

### Managing Deployments
```
bash
# Scale Gateway deployment to 1 replica
kubectl scale deployment --replicas=1 gateway
# Restart Gateway deployment
kubectl rollout restart deployment gateway
# Deploy MongoDB
kubectl apply -f mongodb-service.yaml kubectl apply -f mongodb-deployment.yaml
# View Kubernetes dashboard
k9s
# Enable external access (for Minikube)
minikube tunnel
# Check pod status
kubectl get pods
# View logs of specific pods
kubectl logs -f converter-758b86587c-xqntx kubectl logs -f gateway-5d47ff8f68-r5cz9 kubectl logs -f auth-59f78bd6f9-9rnlb
# Scale Converter deployment
kubectl scale deployment --replicas=1 converter
``` 

## MongoDB Operations

Access and manage MongoDB data:

```bash
# Connect to MongoDB pod
kubectl exec -it mongodb-56f55d77d8-vsh68 -- bash

# List files in pod
ls -la test2.mp3

# Copy a file from MongoDB pod to local machine
kubectl cp mongodb-56f55d77d8-vsh68:/test2.mp3 ./yerel-test2.mp3

# Get a file from GridFS using mongofiles
mongofiles --host localhost --port 27017 --db=mp3s get_id --local=test2.mp3 '{"$oid":"682a3b3b6818b3ab0301244a"}'

# Access MongoDB shell
kubectl exec -it mongodb-56f55d77d8-vsh68 -- mongo

# MongoDB shell commands
show databases;
show collections;
use mp3s;
show collections;
db.fs.files.find()
db.fs.files.find({"_id": ObjectId("682a2026f9f4e37e4f20bb9b")})
```

## API Endpoints
### 1. Login
``` bash
curl --location --request POST 'http://mp3converter.com/login' \
--header 'Authorization: Basic Z2Vvcmdpb0BlbWFpbC5jb206QWRtaW4xMjM='
```
- **Method**: POST
- **URL**: /login
- **Authentication**: Basic Auth (Base64 encoded username:password)
- **Returns**: JWT token

This endpoint authenticates a user with Basic Auth and returns a JWT token for use in subsequent requests.
### 2. Upload Video
``` bash
curl --location 'http://mp3converter.com/upload' \
--header 'Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VybmFtZSI6Imdlb3JnaW9AZW1haWwuY29tIiwiZXhwIjoxNzQ3NjgxMzEwLCJpYXQiOjE3NDc1OTQ5MTAsImFkbWluIjp0cnVlfQ.zNoh5WGEWYOob0j_he052JFr4S7ZQIO_ylOPcjTstlc' \
--form 'file=@"/C:/Users/selcuk/Desktop/system_design/python/src/converter/test2.mkv"'
```
- **Method**: POST
- **URL**: /upload
- **Authentication**: Bearer JWT token
- **Body**: Form data with video file
- **Permissions**: Admin only
- **Returns**: Success message

This endpoint allows uploading a video file for conversion to MP3. The file is stored in MongoDB GridFS, and a message is sent to RabbitMQ for processing.
### 3. Download MP3
``` bash
curl --location 'http://mp3converter.com/download?fid=682a46616818b3ab0301244e' \
--header 'Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VybmFtZSI6Imdlb3JnaW9AZW1haWwuY29tIiwiZXhwIjoxNzQ3NjgxMzEwLCJpYXQiOjE3NDc1OTQ5MTAsImFkbWluIjp0cnVlfQ.zNoh5WGEWYOob0j_he052JFr4S7ZQIO_ylOPcjTstlc'
```
- **Method**: GET
- **URL**: /download
- **Query Parameters**: fid (file ID in MongoDB)
- **Authentication**: Bearer JWT token
- **Permissions**: Admin only
- **Returns**: MP3 file

This endpoint downloads the converted MP3 file by its ID from MongoDB GridFS.
## Notification Service
The notification service sends emails when conversion is complete. It requires Gmail credentials in a Kubernetes secret:
``` yaml
apiVersion: v1
kind: Secret
metadata:
  name: notification-secret
stringData:
  GMAIL_ADDRESS: "microleyla234@gmail.com"
  GMAIL_PASSWORD: "your-app-password"
type: Opaque
```
Since Google no longer allows "Less Secure App Access", you must:
1. Enable 2-Factor Authentication on your Google account
2. Generate an App Password at [https://myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
3. Use this App Password in your secret

## Email Service Configuration
To fix the SMTP authentication error, update the email.py file:
``` python
import smtplib, os, json
from email.message import EmailMessage


def notification(message):
    try:
        message = json.loads(message)
        mp3_fid = message["mp3_fid"]
        sender_address = os.environ.get("GMAIL_ADDRESS")
        sender_password = os.environ.get("GMAIL_PASSWORD")
        receiver_address = message["username"]

        msg = EmailMessage()
        msg.set_content(f"mp3 file_id: {mp3_fid} is now ready!")
        msg["Subject"] = "MP3 Download"
        msg["From"] = sender_address
        msg["To"] = receiver_address

        session = smtplib.SMTP("smtp.gmail.com", 587)
        session.starttls()
        session.login(sender_address, sender_password)
        session.send_message(msg)
        session.quit()
        print("Mail Sent")
        return None
    except Exception as err:
        print(f"Error sending email: {err}")
        return err
```
## Architecture
- **Gateway**: Flask API service that handles requests and authentication
- **Auth**: Manages user credentials and JWT tokens
- **Converter**: Uses FFmpeg to convert videos to MP3 format
- **Notification**: Sends email notifications using SMTP
- **MongoDB**: Stores files using GridFS
- **RabbitMQ**: Message queue for asynchronous processing

## Workflow
1. User authenticates and receives JWT token
2. User uploads video file
3. Gateway stores video and sends message to RabbitMQ
4. Converter processes video to MP3
5. User receives email notification
6. User downloads MP3 file using provided ID

## Troubleshooting
- Check pod logs: `kubectl logs -f <pod-name>`
- Verify MongoDB connection: `kubectl exec -it <mongodb-pod> -- mongo`
- Check email configuration: Ensure App Password is correct
- Restart services: `kubectl rollout restart deployment <deployment-name>`
