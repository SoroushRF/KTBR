# 🚀 KTBR Bot - Google Cloud Deployment Guide

This guide will walk you through deploying your Telegram bot on Google Cloud Compute Engine from **absolute zero**. No prior cloud experience required.

---

## 📋 Table of Contents

1. [Create a Google Cloud Account](#step-1-create-a-google-cloud-account)
2. [Create a New Project](#step-2-create-a-new-project)
3. [Enable Billing (Free Trial)](#step-3-enable-billing-free-trial)
4. [Create a Virtual Machine](#step-4-create-a-virtual-machine)
5. [Connect to Your VM](#step-5-connect-to-your-vm)
6. [Install Docker](#step-6-install-docker)
7. [Upload Your Bot Code](#step-7-upload-your-bot-code)
8. [Configure and Run](#step-8-configure-and-run)
9. [Verify It's Working](#step-9-verify-its-working)
10. [Make It Persistent](#step-10-make-it-persistent)
11. [Monitoring & Maintenance](#step-11-monitoring--maintenance)

---

## Step 1: Create a Google Cloud Account

### 1.1 Go to Google Cloud
1. Open your browser and go to: **https://cloud.google.com**
2. Click the **"Get started for free"** button (top right)

### 1.2 Sign In
1. Sign in with your Google account (Gmail)
2. If you don't have one, create a new Google account first

### 1.3 Free Trial
- Google Cloud offers **$300 free credits** for 90 days
- You need to add a credit card, but **you won't be charged** during the trial
- After the trial, you must manually upgrade to be charged

---

## Step 2: Create a New Project

### 2.1 Access the Console
1. After signing up, you'll be at: **https://console.cloud.google.com**
2. You should see a dashboard

### 2.2 Create Project
1. Click the **project dropdown** at the top left (next to "Google Cloud")
   - It might say "Select a project" or show an existing project name
2. Click **"NEW PROJECT"** (top right of the popup)
3. Fill in:
   - **Project name**: `ktbr-bot` (or any name you like)
   - **Location**: Leave as default (No organization)
4. Click **"CREATE"**
5. Wait 10-30 seconds for it to create
6. Click the **project dropdown** again and select your new project

---

## Step 3: Enable Billing (Free Trial)

If you haven't already set up billing:

1. Click the **hamburger menu** (☰) at the top left
2. Go to **"Billing"**
3. Click **"LINK A BILLING ACCOUNT"**
4. Follow the prompts to set up your free trial
5. Add your credit card (required but won't be charged)

---

## Step 4: Create a Virtual Machine

This is where your bot will run 24/7.

### 4.1 Navigate to Compute Engine
1. Click the **hamburger menu** (☰) at the top left
2. Scroll down to **"Compute Engine"**
3. Click **"VM instances"**
4. If this is your first time, click **"ENABLE"** to enable the Compute Engine API
   - This takes 1-2 minutes

### 4.2 Create a VM Instance
1. Click **"CREATE INSTANCE"** (blue button at top)

### 4.3 Configure the VM

Fill in these settings:

#### Basic Info
| Setting | Value |
|---------|-------|
| **Name** | `ktbr-bot` |
| **Region** | `us-central1` (Iowa) - cheapest |
| **Zone** | `us-central1-a` |

#### Machine Configuration
1. Click **"GENERAL PURPOSE"** tab (should be selected)
2. **Series**: `E2`
3. **Machine type**: `e2-micro` (2 vCPU, 1 GB memory)
   - This is **FREE TIER eligible** (always free)

#### Boot Disk
1. Click **"CHANGE"** under Boot disk
2. Configure:
   | Setting | Value |
   |---------|-------|
   | **Operating system** | `Debian` |
   | **Version** | `Debian GNU/Linux 12 (bookworm)` |
   | **Boot disk type** | `Standard persistent disk` |
   | **Size (GB)** | `10` |
3. Click **"SELECT"**

#### Firewall
- ☑️ Check **"Allow HTTP traffic"**
- ☑️ Check **"Allow HTTPS traffic"**

### 4.4 Create the VM
1. Scroll down and click **"CREATE"**
2. Wait 30-60 seconds for the VM to spin up
3. You'll see a green checkmark ✅ when it's ready

---

## Step 5: Connect to Your VM

### 5.1 SSH via Browser (Easiest)
1. On the VM instances page, find your `ktbr-bot` VM
2. Click the **"SSH"** button under the "Connect" column
3. A new browser window will open with a terminal
4. Wait for it to connect (10-20 seconds)

You should see something like:
```
username@ktbr-bot:~$
```

**You're now inside your cloud server!** 🎉

---

## Step 6: Install Docker

Run these commands **one by one** in the SSH terminal:

### 6.1 Update the System
```bash
sudo apt-get update
```
Wait for it to finish (shows package lists).

### 6.2 Install Required Packages
```bash
sudo apt-get install -y ca-certificates curl gnupg
```

### 6.3 Add Docker's Official GPG Key
```bash
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
```

### 6.4 Add Docker Repository
```bash
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
```

### 6.5 Install Docker
```bash
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

### 6.6 Allow Running Docker Without sudo
```bash
sudo usermod -aG docker $USER
```

### 6.7 Apply Group Changes
```bash
newgrp docker
```

### 6.8 Verify Docker Works
```bash
docker --version
```
You should see something like: `Docker version 24.x.x`

---

## Step 7: Upload Your Bot Code

### Option A: Clone from GitHub (Recommended)

If your code is on GitHub:

```bash
# Clone your repository
git clone https://github.com/YOUR_USERNAME/KTBR.git

# Enter the directory
cd KTBR
```

Replace `YOUR_USERNAME` with your actual GitHub username.

---

### Option B: Upload Files Manually

If your code is NOT on GitHub:

#### 7B.1 Open Cloud Shell File Upload
1. In the SSH window, click the **gear icon** (⚙️) at the top right
2. Click **"Upload file"**
3. This opens a file picker

#### 7B.2 Create a ZIP of Your Project
On your Windows PC:
1. Go to `C:\Users\sorou\OneDrive\Desktop\KTBR`
2. Select these files:
   - `bot.py`
   - `Dockerfile`
   - `docker-compose.yml`
   - `requirements.txt`
   - `face_detection_yunet_2023mar.onnx`
3. Right-click → **Send to** → **Compressed (zipped) folder**
4. Name it `ktbr.zip`

#### 7B.3 Upload and Extract
1. Upload `ktbr.zip` using the file upload dialog
2. In the SSH terminal, run:
```bash
# Create directory
mkdir -p ~/KTBR

# Install unzip if needed
sudo apt-get install -y unzip

# Unzip the files
unzip ktbr.zip -d ~/KTBR

# Enter the directory
cd ~/KTBR
```

---

## Step 8: Configure and Run

### 8.1 Create the .env File
```bash
nano .env
```

This opens a text editor. Type the following (replace with your actual values):

```
BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
ALLOWED_USERNAMES=your_telegram_username
```

**To save and exit nano:**
1. Press `Ctrl + X`
2. Press `Y` (yes to save)
3. Press `Enter` (confirm filename)

### 8.2 Create the Data Directory
```bash
mkdir -p data
```

### 8.3 Build and Run the Container
```bash
docker compose up -d --build
```

**What this does:**
- `--build`: Builds the Docker image (downloads Python, installs FFmpeg, etc.)
- `-d`: Runs in the background (detached mode)

This will take **2-5 minutes** the first time as it:
- Downloads the Python base image
- Installs FFmpeg
- Installs all Python dependencies

### 8.4 Check the Logs
```bash
docker compose logs -f
```

You should see:
```
ktbr-face-blur-bot  | 2026-01-07 16:57:42,123 - __main__ - INFO - Starting bot...
```

**Press `Ctrl + C` to exit the logs** (the bot keeps running in the background).

---

## Step 9: Verify It's Working

### 9.1 Test on Telegram
1. Open Telegram on your phone or desktop
2. Find your bot (search for the username you gave it in BotFather)
3. Send `/start`
4. You should get the welcome message!

### 9.2 Check Container Status
```bash
docker compose ps
```

You should see:
```
NAME                  STATUS
ktbr-face-blur-bot    Up X minutes
```

---

## Step 10: Make It Persistent

Your bot is running, but what happens if the VM restarts? Let's make it automatic.

### 10.1 Enable Auto-restart for Docker
```bash
sudo systemctl enable docker
```

### 10.2 The Container Already Auto-restarts
In your `docker-compose.yml`, we have:
```yaml
restart: unless-stopped
```

This means the container will automatically restart:
- ✅ If it crashes
- ✅ If the VM reboots
- ❌ Only stops if you manually stop it

### 10.3 Test It (Optional)
```bash
# Restart the VM
sudo reboot
```

Wait 1-2 minutes, SSH back in, and check:
```bash
cd ~/KTBR
docker compose ps
```

The bot should be running! 🎉

---

## Step 11: Monitoring & Maintenance

### View Real-time Logs
```bash
cd ~/KTBR
docker compose logs -f
```

### View Last 100 Lines
```bash
docker compose logs --tail=100
```

### Stop the Bot
```bash
docker compose down
```

### Start the Bot
```bash
docker compose up -d
```

### Restart the Bot
```bash
docker compose restart
```

### Update the Bot (after code changes)
```bash
# If using GitHub:
git pull

# Rebuild and restart
docker compose up -d --build
```

### Check Disk Space
```bash
df -h
```

### Clean Up Docker (free disk space)
```bash
docker system prune -a
```

---

## 💰 Cost Estimate

| Resource | Monthly Cost |
|----------|-------------|
| e2-micro VM (free tier) | **$0** |
| 10 GB disk | ~$0.40 |
| Network egress | ~$0.10 (minimal) |
| **Total** | **~$0.50/month** |

With the **$300 free trial credits**, you can run this for **50+ months** (over 4 years)!

---

## 🆘 Troubleshooting

### "Permission denied" when running docker
```bash
sudo usermod -aG docker $USER
newgrp docker
```

### Bot not responding
```bash
# Check logs for errors
docker compose logs --tail=50

# Restart the container
docker compose restart
```

### "Cannot connect to Docker daemon"
```bash
sudo systemctl start docker
```

### Out of disk space
```bash
# Clean up Docker
docker system prune -a

# Check what's using space
du -sh /*
```

### SSH window closed accidentally
Just click **SSH** again in the Cloud Console to reconnect. Your bot keeps running!

---

## 🎉 You're Done!

Your KTBR Face Blur Bot is now running 24/7 on Google Cloud!

**Quick Reference:**
- **SSH to server**: Google Cloud Console → Compute Engine → VM instances → SSH
- **Bot logs**: `cd ~/KTBR && docker compose logs -f`
- **Restart bot**: `cd ~/KTBR && docker compose restart`

---

## Next Steps (Optional)

- [ ] Set up a custom domain
- [ ] Add monitoring/alerting
- [ ] Set up automatic backups
- [ ] Create a GitHub Actions CI/CD pipeline

