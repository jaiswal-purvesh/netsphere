[Unit]
Description=NetSphere (compose stack)
Wants=network-online.target
After=network-online.target @ENGINE_UNIT@

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=@ROOT@
Environment=NETSPHERE_ENGINE=@ENGINE@
ExecStart=@ROOT@/deploy/netsphere up
ExecStop=@ROOT@/deploy/netsphere down
TimeoutStartSec=600
TimeoutStopSec=120

[Install]
WantedBy=@WANTED_BY@
