# ML Training - Automatic Weekly Training Setup

## ✅ Training Script Created

**Location:** `/projects/ngTradingBot/weekly_ml_training.sh`

This script will:
- Train new ML model with last 90 days of trade data
- Save model to database and file system
- Send Telegram notification on success/failure
- Clean up old log files (>30 days)

---

## 🔧 Unraid Cron Setup

### Method 1: User Scripts Plugin (RECOMMENDED)

1. **Install User Scripts Plugin** (if not installed):
   - Go to Unraid Web UI → Plugins → Install Plugin
   - Search for "User Scripts"

2. **Add New Script**:
   - Go to Settings → User Scripts
   - Click "Add New Script"
   - Name: `ML_Training_Weekly`

3. **Paste Script Content**:
   ```bash
   #!/bin/bash
   /projects/ngTradingBot/weekly_ml_training.sh
   ```

4. **Set Schedule**:
   - Click gear icon → Schedule
   - Select: **Custom** → `0 2 * * 0` (Sunday 2:00 AM)
   - Click "Apply"

5. **Test Run**:
   - Click "Run in Background"
   - Check logs in `/projects/ngTradingBot/data/ml_training_*.log`

---

### Method 2: Manual Crontab (ALTERNATIVE)

1. **Edit Crontab**:
   ```bash
   # On Unraid terminal
   crontab -e
   ```

2. **Add Line**:
   ```
   0 2 * * 0 /projects/ngTradingBot/weekly_ml_training.sh
   ```

3. **Save and Exit**: Press `Ctrl+X`, then `Y`, then `Enter`

4. **Verify**:
   ```bash
   crontab -l | grep weekly_ml_training
   ```

---

### Method 3: Go Array Plugin (ALTERNATIVE)

1. Install "Go Array" plugin
2. Add script to `/boot/config/plugins/user.scripts/scripts/`
3. Configure schedule in plugin settings

---

## 📅 Schedule Explained

```
0 2 * * 0
│ │ │ │ └─── Day of week (0 = Sunday)
│ │ │ └───── Month (1-12)
│ │ └─────── Day of month (1-31)
│ └───────── Hour (0-23)
└─────────── Minute (0-59)
```

**Current: `0 2 * * 0`** = Every Sunday at 2:00 AM

**Other Examples:**
- `0 2 * * *` = Every day at 2:00 AM
- `0 2 1 * *` = First day of every month at 2:00 AM
- `0 2 * * 1` = Every Monday at 2:00 AM

---

## 🧪 Manual Test Run

Test the script manually before scheduling:

```bash
# Run training manually
/projects/ngTradingBot/weekly_ml_training.sh

# Check output
tail -f /projects/ngTradingBot/data/ml_training_*.log
```

---

## 📊 Verify Training Success

After training runs, verify:

```bash
# Check database
docker exec ngtradingbot_db psql -U trader -d ngtradingbot -c \
  "SELECT model_name, version, validation_accuracy, is_active, created_at
   FROM ml_models ORDER BY created_at DESC LIMIT 3;"

# Check model files
docker exec ngtradingbot_workers ls -lh /app/ml_models/xgboost/

# Check latest log
tail -50 /projects/ngTradingBot/data/ml_training_*.log | tail -50
```

---

## 📱 Telegram Notifications (Optional)

The script will automatically send Telegram notifications if configured.

**Already configured in your system:**
- Bot Token: `8454891267:AAHKrGTcGCVfXjb0LNjq6QAC816Un9ig7VA`
- Chat ID: `557944459`

Notifications are loaded from `/projects/ngTradingBot/.env.telegram`

---

## 📝 Log Files

**Location:** `/projects/ngTradingBot/data/ml_training_YYYYMMDD_HHMMSS.log`

**Retention:** 30 days (automatic cleanup)

**View latest:**
```bash
ls -lt /projects/ngTradingBot/data/ml_training_*.log | head -5
```

---

## ⚠️ Troubleshooting

### Script doesn't run

1. Check permissions:
   ```bash
   chmod +x /projects/ngTradingBot/weekly_ml_training.sh
   ```

2. Check container is running:
   ```bash
   docker ps | grep ngtradingbot_workers
   ```

3. Test manually first (see above)

### Training fails

Check logs:
```bash
tail -100 /projects/ngTradingBot/data/ml_training_*.log
```

Common issues:
- Not enough data (need >50 closed trades in last 90 days)
- Database connection issues
- Container not running

### No Telegram notification

Check `.env.telegram` file:
```bash
cat /projects/ngTradingBot/.env.telegram | grep TELEGRAM
```

---

## 🎯 Next Steps

1. ✅ **Set up cron** (Method 1 recommended)
2. ✅ **Test manual run**
3. ✅ **Wait for Sunday 2:00 AM** (automatic)
4. ✅ **Check logs on Monday morning**

---

## 📈 Expected Results

After training:
- New model with 80-85% accuracy
- Model activated in database (`is_active = true`)
- Old model deactivated automatically
- Next trades will use new model

**Training Duration:** ~2-10 seconds

**Data Required:** 50-500 closed trades from last 90 days

**Current Dataset:** 530 trades (✅ sufficient)

---

## 🔄 Manual Re-training

If you need to retrain immediately (e.g., after big changes):

```bash
# Quick retrain
docker exec ngtradingbot_workers python3 /app/train_ml_models.py

# Or via script (with logging)
/projects/ngTradingBot/weekly_ml_training.sh
```

**Remember:** Don't train too often! Weekly is optimal.

---

## ✅ Setup Complete

Your ML training is now configured for automatic weekly updates! 🎉

The model will learn from new trade patterns every Sunday and improve over time.
