#!/usr/bin/env sh

systemctl disable --now hivey-back-end 2>/dev/null
rm -f /usr/lib/systemd/system/hivey-back-end.service
cp -f /var/www/hivey/backend/misc/conf/hivey-back-end.service /usr/lib/systemd/system/hivey-back-end.service
systemctl daemon-reload
systemctl enable --now hivey-back-end
