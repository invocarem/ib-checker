# ibdev2netdev
```txt
rocep1s0f0 port 1 ==> enp1s0f0np0 (Down)
rocep1s0f1 port 1 ==> enp1s0f1np1 (Up)
roceP2p1s0f0 port 1 ==> enP2p1s0f0np0 (Down)
roceP2p1s0f1 port 1 ==> enP2p1s0f1np1 (Up)
```

# netplan/40-cx7.yaml
```yaml
network:
  version: 2
  ethernets:
    enp1s0f1np1:
      dhcp4: no
      dhcp6: no
      link-local: []
      mtu: 9000
      addresses: [192.168.100.11/24]
    enP2p1s0f1np1:
      dhcp4: no
      dhcp6: no
      link-local: []
      mtu: 9000
      addresses: [192.168.200.17/24]
```

# ibv_devinfo
```
hca_id:	rocep1s0f0
	transport:			InfiniBand (0)
	fw_ver:				28.45.4028
	node_guid:			4cbb:4703:002d:1a16
	sys_image_guid:			4cbb:4703:002d:1a16
	vendor_id:			0x02c9
	vendor_part_id:			4129
	hw_ver:				0x0
	board_id:			NVD0000000087
	phys_port_cnt:			1
		port:	1
			state:			PORT_DOWN (1)
			max_mtu:		4096 (5)
			active_mtu:		1024 (3)
			sm_lid:			0
			port_lid:		0
			port_lmc:		0x00
			link_layer:		Ethernet

hca_id:	rocep1s0f1
	transport:			InfiniBand (0)
	fw_ver:				28.45.4028
	node_guid:			4cbb:4703:002d:1a17
	sys_image_guid:			4cbb:4703:002d:1a16
	vendor_id:			0x02c9
	vendor_part_id:			4129
	hw_ver:				0x0
	board_id:			NVD0000000087
	phys_port_cnt:			1
		port:	1
			state:			PORT_ACTIVE (4)
			max_mtu:		4096 (5)
			active_mtu:		4096 (5)
			sm_lid:			0
			port_lid:		0
			port_lmc:		0x00
			link_layer:		Ethernet

hca_id:	roceP2p1s0f0
	transport:			InfiniBand (0)
	fw_ver:				28.45.4028
	node_guid:			4cbb:4703:002d:1a1a
	sys_image_guid:			4cbb:4703:002d:1a16
	vendor_id:			0x02c9
	vendor_part_id:			4129
	hw_ver:				0x0
	board_id:			NVD0000000087
	phys_port_cnt:			1
		port:	1
			state:			PORT_DOWN (1)
			max_mtu:		4096 (5)
			active_mtu:		1024 (3)
			sm_lid:			0
			port_lid:		0
			port_lmc:		0x00
			link_layer:		Ethernet

hca_id:	roceP2p1s0f1
	transport:			InfiniBand (0)
	fw_ver:				28.45.4028
	node_guid:			4cbb:4703:002d:1a1b
	sys_image_guid:			4cbb:4703:002d:1a16
	vendor_id:			0x02c9
	vendor_part_id:			4129
	hw_ver:				0x0
	board_id:			NVD0000000087
	phys_port_cnt:			1
		port:	1
			state:			PORT_ACTIVE (4)
			max_mtu:		4096 (5)
			active_mtu:		4096 (5)
			sm_lid:			0
			port_lid:		0
			port_lmc:		0x00
			link_layer:		Ethernet
```
