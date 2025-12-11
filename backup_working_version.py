#!/usr/bin/env python3
"""
Backup script to create a snapshot of the current working NFL Stats system.
Run this script to create a timestamped backup of all critical files.
"""

import os
import shutil
from datetime import datetime
import zipfile

def create_backup():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = f"backup_working_{timestamp}"
    
    # Critical files to backup
    files_to_backup = [
        "pipeline_config.py",
        "odds_api.py", 
        "test_thresholds.py",
        "models.py",
        "app.py",
        "index.html",
        "Odds_vs_Stats_Check.py",
        "probability_calc.py",
        "team_stats.py",
        "target_share_calc.py",
        "opportunity_adjustment.py",
        "game_script_adjustment.py",
        "save_to_db.py",
        "fetch_stats.py",
        "nfl_stats.db",
        "team_stats_data.json"
    ]
    
    # Create backup directory
    os.makedirs(backup_dir, exist_ok=True)
    
    # Copy files
    copied_files = []
    for file in files_to_backup:
        if os.path.exists(file):
            shutil.copy2(file, backup_dir)
            copied_files.append(file)
            print(f"[OK] Backed up: {file}")
        else:
            print(f"[MISSING] {file}")
    
    # Create zip archive
    zip_name = f"{backup_dir}.zip"
    with zipfile.ZipFile(zip_name, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for file in copied_files:
            zipf.write(os.path.join(backup_dir, file), file)
    
    # Remove temporary directory
    shutil.rmtree(backup_dir)
    
    print(f"\nBackup created: {zip_name}")
    print(f"Contains {len(copied_files)} files")
    
    return zip_name

if __name__ == "__main__":
    create_backup()