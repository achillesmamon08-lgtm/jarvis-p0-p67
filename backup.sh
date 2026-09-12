#!/bin/bash
# Auto-backup JARVIS codebase to prevent PRoot filesystem loss
BACKUP_DIR="/data/data/com/termux/files/home/JARVIS_BACKUP_$(date +%Y%m%d)"
mkdir -p "$BACKUP_DIR"
cp -r /data/data/com/termux/files/home/JARVIS/* "$BACKUP_DIR/" 2>/dev/null
echo "Backup created at $BACKUP_DIR"
