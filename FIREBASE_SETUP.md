# Firebase Configuration for Push Notifications
# To set up Firebase Cloud Messaging (FCM) for push notifications:

## Quick Test
Run the test script to verify your setup:
```bash
cd backend
python test_firebase.py
```

## Current Setup
The application is configured to load Firebase credentials from `backend.json` in the backend directory.

## If you need to update Firebase configuration:
1. Go to Firebase Console: https://console.firebase.google.com/
2. Select your project (or create a new one)
3. Go to Project Settings > Service Accounts
4. Generate a new private key and download the JSON file
5. Replace the contents of `backend.json` with the downloaded credentials

## Testing
Once configured, you can test push notifications from the admin panel:
- Go to Admin > Notifications
- Enter a title and message
- Click "Send Push Notification"
- Check the backend logs for delivery status

## Important Notes
- Make sure your Firebase project has Cloud Messaging enabled
- For iOS apps, you'll need to upload your APNs certificate to Firebase
- For Android apps, the FCM token will be automatically handled by the Capacitor plugin
- The backend.json file contains your service account credentials - keep it secure!
