#!/bin/bash
# Monitor CONN preprocessing progress

echo "CONN Preprocessing Monitor"
echo "=========================="
echo ""

# Check running workers
echo "Active Workers:"
ps aux | grep MATLAB_maca64 | grep conn_jobmanager | wc -l | awk '{print "  "$1" workers running"}'
echo ""

# CPU usage
echo "CPU Usage:"
ps aux | grep MATLAB_maca64 | grep conn_jobmanager | awk '{sum+=$3} END {print "  "sum"% total (avg "sum/NR"% per worker)"}'
echo ""

# Latest activity from logs
echo "Latest Progress:"
tail -1 /Volumes/Work/Work/long/conn_project/conn_longitudinal.qlog/*/node.*.stdlog 2>/dev/null | grep -E "Running|Completed" | tail -5
echo ""

# Count completed realignment files
COMPLETED=$(find /Volumes/Work/Work/long/conn_project -name "rp_*.txt" 2>/dev/null | wc -l | tr -d ' ')
echo "Completed Realignments: $COMPLETED / 48 sessions"
echo ""

# Estimate time remaining (rough)
if [ "$COMPLETED" -gt 0 ]; then
    PERCENT=$((COMPLETED * 100 / 48))
    echo "Progress: $PERCENT% of realignment complete"
fi
