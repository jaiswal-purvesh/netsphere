[Unit]
Description=NetSphere database backup

[Service]
Type=oneshot
WorkingDirectory=@ROOT@
Environment=NETSPHERE_ENGINE=@ENGINE@
ExecStart=@ROOT@/deploy/netsphere backup
