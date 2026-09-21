# NexusNode Timetable & Google Calendar Setup Guide

Welcome to NexusNode! This guide will walk you through connecting your UPES academic schedule to your personal Google Calendar in 5 simple steps.

---

## 1. Quick Setup in 5 Steps

### Step 1: Connect Your Google Calendar
1. Log into your NexusNode account.
2. Navigate to **Academics & Calendar**.
3. Under **Step 1: Connect Google Calendar**, click **Connect Google Calendar**.
4. Authorize NexusNode to write scheduled classes to your Google Calendar.
5. Once authorized, you will see your connected Google email with a green `CONNECTED ✓` badge.

### Step 2: Connect Your UPES Account
1. Enter your UPES institutional email (e.g. `firstname.sapid@stu.upes.ac.in`).
   > **Note:** The UPES login system requires your full institutional email address, not just numeric SAP ID.
2. Enter your UPES Portal password.
3. Click **Save UPES Credentials**.
4. Your credentials are encrypted immediately using **AES-256-GCM**. NexusNode never stores or logs your plaintext password.

### Step 3: Choose Target Calendar & Sync Preferences
1. Select the Google Calendar where your classes should appear (e.g. `Primary Calendar` or a dedicated `Classes` calendar).
2. Click **Save Calendar Selection**.
3. NexusNode will synchronize your full semester schedule and automatically check for updates every 3 hours.

### Step 4: Initial Timetable Reconciliation
1. Click **Sync Timetable Now**.
2. NexusNode connects to UPES, downloads your authoritative timetable, and creates your calendar events with course names, room numbers, and faculty details.

### Step 5: Verification & Student Dashboard
1. Review your session count and synced events in Step 5.
2. Click **Go to Dashboard** to view today's schedule, live card-punch status, and the 75% attendance bunk planner!

---

## 2. Security & Data Privacy

- **Encryption at Rest**: Your UPES password is encrypted with **AES-256-GCM** using isolated encryption keys specific to your user account.
- **Decryption on Demand**: NexusNode decrypts your password only in memory when authenticating with UPES services.
- **Zero Logging**: Plaintext passwords and session cookies are never written to log files or exported in API responses.
- **Google Permissions**: NexusNode requests only the permissions necessary to manage your academic calendar.

---

## 3. Automatic Updates & Schedule Changes

- **3-Hour Reconciliation**: NexusNode automatically queries the UPES portal every 3 hours.
- **Dynamic Updates**: If a faculty member reschedules a class, changes a lecture room, or cancels a lecture, NexusNode updates or removes the calendar event automatically.
- **LKG (Last Known Good) Fallback**: If the UPES portal is temporarily undergoing maintenance, NexusNode displays your cached timetable so you always know your class schedule.

---

## 4. Troubleshooting & Management

### Changing Your NexusNode Password
- Open the user menu (top right) $\rightarrow$ **Change Password**.
- Enter your current password and choose a new password (min 6 characters).

### Updating UPES Password
- If you change your password on the UPES portal, go to **Academics & Calendar** $\rightarrow$ **Integration Controls** $\rightarrow$ click **Reauthenticate UPES** or enter your new password in the setup wizard.

### Manual Timetable JSON Upload
- If the UPES portal is temporarily unreachable during your initial setup, you can export your timetable JSON and upload it under **Integration Controls** $\rightarrow$ **Upload JSON**.

### Disconnecting & Erasing Data
- You can disconnect anytime:
  - Click **Disconnect Google** to remove your OAuth tokens.
  - Click **Remove UPES Credentials** to permanently wipe your encrypted credentials from the system.
