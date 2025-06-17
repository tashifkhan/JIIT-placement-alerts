# SuperSet Telegram Bot - User Management & Scheduling Guide

## What's Been Implemented

### ✅ User Registration System

- Users can start the bot with `/start` to register
- Automatic user database management
- User reactivation if they were previously inactive
- Proper handling of existing active users

### ✅ Database Management

- MongoDB collection for users (`Users` table)
- User fields: `user_id`, `username`, `first_name`, `last_name`, `is_active`, `created_at`, `updated_at`
- Automatic user activation/deactivation
- User statistics and management tools

### ✅ Scheduled Broadcasting (3 times daily)

- 12:00 AM IST (Midnight)
- 12:00 PM IST (Noon)
- 6:00 PM IST (Evening)
- Broadcasts to ALL registered users simultaneously

### ✅ Bot Commands

- `/start` - Register for notifications (or reactivate)
- `/stop` - Unsubscribe from notifications
- `/status` - Check subscription status with debug info

### ✅ Management Tools

- `test_user_management.py` - Test user system
- `fix_users.py` - Fix user activation issues
- `scripts/manage_users.py` - Manual user management

## How to Run

### Option 1: Full Bot Server with Scheduler (Recommended)

```bash
python app.py
```

This will:

- Start Telegram bot to handle user interactions
- Schedule scraping + broadcasting 3 times daily
- Run continuously

### Option 2: One-time Run (Testing)

```bash
python app.py --run-once
```

### Option 3: Test User Management

```bash
python test_user_management.py
```

### Option 4: Fix User Issues

```bash
python fix_users.py
```

## 📱 For Users (Your Subscribers)

### How to Subscribe:

1. Find your bot on Telegram
2. Send `/start`
3. Bot will register them and confirm subscription

### How to Check Status:

- Send `/status` to see if they're subscribed

### How to Unsubscribe:

- Send `/stop` to stop receiving notifications

## 🔧 Technical Details

### Database Structure:

```javascript
// Users Collection
{
  "user_id": 1234567890,        // Telegram user ID
  "username": "john_doe",       // Telegram username
  "first_name": "John",         // User's first name
  "last_name": "Doe",          // User's last name (optional)
  "is_active": true,           // Whether user wants notifications
  "created_at": ISODate(),     // When user first registered
  "updated_at": ISODate()      // Last update timestamp
}
```

### Broadcasting Logic:

1. Bot scrapes SuperSet for new posts
2. Saves new posts to database
3. Gets all active users from Users collection
4. Sends each new post to ALL active users
5. Marks posts as sent after successful broadcast

### User Registration Logic:

1. User sends `/start`
2. Bot checks if user exists in database
3. If new user: Creates new record with `is_active: true`
4. If existing inactive user: Reactivates them
5. If existing active user: Shows welcome back message

## 🐞 Troubleshooting

### If users appear inactive after signing up:

```bash
python fix_users.py
```

### To check user status manually:

```bash
python scripts/manage_users.py
```

### To test the system:

```bash
python test_user_management.py
```

### Common Issues:

1. **"User shows as inactive"** - Run `fix_users.py` to reactivate all users
2. **"Bot not responding"** - Check `TELEGRAM_BOT_TOKEN` in `.env`
3. **"Database connection failed"** - Check `MONGO_CONNECTION_STR` in `.env`
4. **"No users receiving messages"** - Run `test_user_management.py` to debug

## 📊 Monitoring

### Check user statistics:

The bot shows user stats when running:

```
👥 User Statistics:
   Total users: 5
   Active users: 5
   Inactive users: 0
```

### View all users:

```bash
python scripts/manage_users.py
# Select option 2 to list all users
```

## 🎯 Key Features Summary

✅ **Multi-user broadcasting** - Sends to all registered users  
✅ **User self-service** - Users can subscribe/unsubscribe themselves  
✅ **Automatic scheduling** - Runs 3 times daily without intervention  
✅ **Database persistence** - All users stored in MongoDB  
✅ **Error handling** - Handles blocked users, network issues  
✅ **Management tools** - Scripts to fix issues and monitor users  
✅ **Debug capabilities** - Comprehensive logging and testing

## 🚀 Ready to Deploy!

Your bot is now ready for production use. Users can:

1. Find your bot on Telegram
2. Send `/start` to subscribe
3. Automatically receive job notifications 3 times daily
4. Manage their subscription with `/stop` and `/status`

The system will automatically handle user management, scheduling, and broadcasting!
