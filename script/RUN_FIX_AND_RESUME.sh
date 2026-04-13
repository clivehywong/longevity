#!/bin/bash
# Wrapper script to fix CONN coregistration issue and resume preprocessing

echo "========================================="
echo "CONN Fix and Resume - Wrapper Script"
echo "========================================="
echo ""
echo "This script will:"
echo "  1. Load CONN project"
echo "  2. Change coregistration reference: mean → first volume"
echo "  3. Resume preprocessing (skips completed steps)"
echo ""
echo "Press Ctrl+C to cancel, or Enter to continue..."
read

# Run MATLAB with the fix script
/Applications/MATLAB_R2024b.app/bin/matlab -nodisplay -nosplash -r "cd('/Volumes/Work/Work/long/script'); conn_fix_and_resume; exit"

echo ""
echo "========================================="
echo "Fix script completed"
echo "========================================="
echo ""
echo "Check the output above for status."
echo "Monitor ongoing progress with:"
echo "  bash script/monitor_conn_progress.sh"
