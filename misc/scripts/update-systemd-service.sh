#!/usr/bin/env sh

systemctl disable --now hivey-back.target 2>/dev/null
systemctl disable --now hivey-back-api 2>/dev/null
systemctl disable --now hivey-back-worker 2>/dev/null

rm -f /usr/lib/systemd/system/hivey-back.target
rm -f /usr/lib/systemd/system/hivey-back-workder.service
rm -f /usr/lib/systemd/system/hivey-back-api.service
cp -f /var/www/hivey/backend/misc/conf/hivey-back.target /usr/lib/systemd/system/hivey-back.target
cp -f /var/www/hivey/backend/misc/conf/hivey-back-api.service /usr/lib/systemd/system/hivey-back-api.service
cp -f /var/www/hivey/backend/misc/conf/hivey-back-worker.service /usr/lib/systemd/system/hivey-back-worker.service

systemctl daemon-reload
# systemctl enable --now hivey-back.target
systemctl restart hivey-back-api
systemctl restart hivey-back-worker

