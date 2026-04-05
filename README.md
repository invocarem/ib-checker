# ib-checker

Small utilities to **verify point-to-point connectivity and TCP throughput** between two machines over a **QSFP DAC** (here: two NVIDIA Spark nodes on `192.168.100.0/24`). This repo also holds **notes** (`spark1.md`, `spark2.md`) from `ibdev2netdev`, `ibv_devinfo`, and netplan.

**Conclusion from checks so far:** With `ethtool` reporting **200000 Mb/s**, **Direct Attach Copper**, and **Link detected: yes**, and multi-stream TCP tests reaching **on the order of ~100+ Gb/s** aggregate, the **cable and PHY are behaving as expected** for a 200G DAC. Remaining limits are mostly **TCP stack, CPU, and test method**, not a “bad cable stuck at 10G.”

---

## Requirements

- **Python 3** (stdlib only; no `pip install` for the script)
- On the **host** (not always in minimal containers): `ethtool` for `link-info`

---

## Quick reference: interfaces and IPs

| Node   | Netdev (192.168.100.x link) | Address        |
|--------|-----------------------------|----------------|
| spark1 | `enp1s0f1np1`              | `192.168.100.11` |
| spark2 | `enp1s0f0np0`              | `192.168.100.12` |

Use **`spark1.md` / `spark2.md`** for full `ibv_devinfo` and netplan context.

---

## `verify_dac_link.py`

### 1. Link speed and media (host)

```bash
python3 verify_dac_link.py link-info --iface enp1s0f0np0   # spark2
python3 verify_dac_link.py link-info --iface enp1s0f1np1   # spark1
```

Confirm **Speed** (e.g. `200000Mb/s` for 200G), **Port: Direct Attach Copper** for a DAC, and **Link detected: yes**.

### 2. TCP throughput (two terminals)

**Server (e.g. spark1):**

```bash
python3 verify_dac_link.py server --listen 192.168.100.11 --port 45231 --streams 16
```

**Client (e.g. spark2):**

```bash
python3 verify_dac_link.py client --peer 192.168.100.11 --local-bind 192.168.100.12 \
  --port 45231 --streams 16 --duration 15
```

- **`--local-bind`** forces traffic out the correct interface (your side’s `192.168.100.x` address).
- **`--streams`** must match on **server** and **client**. Single-stream runs are often only a few–tens Gb/s in Python (CPU-bound); **parallel streams** better reflect what the path can carry under TCP.

### 3. Other subcommands

- **`ping-tcp`** — quick TCP connect test.
- **`bidir`** — full-duplex flood on one connection (see `--help`).

---

## How to read the numbers

| Observation | Meaning |
|-------------|--------|
| **~5–15 Gb/s**, one stream, Python | Normal for a single tight `send` loop; **not** proof the link is 10G. |
| **~100+ Gb/s**, many streams | Consistent with a **healthy 200G** path under **TCP + userspace** load. |
| **200000 Mb/s** in `ethtool` | PHY negotiated as expected for the DAC. |
| **Well below** line rate | Expected for **TCP goodput** vs **200G line rate**; try `iperf3` with `-P` for a common lab comparison, or **NCCL/RoCE** for training-relevant traffic. |

---

## Next: NCCL on the system

NCCL chooses a **network plugin**: **InfiniBand/RoCE** (`NET/IB`) when RDMA devices are usable, otherwise **TCP** (`NET/Socket`) on the interface from **`NCCL_SOCKET_IFNAME`** (and related env).

### If you only need TCP over the DAC (simplest)

- Set **`NCCL_SOCKET_IFNAME`** to the **netdev that carries `192.168.100.x`** on **each** node (spark1: `enp1s0f1np1`, spark2: `enp1s0f0np0`).
- Set **`GLOO_SOCKET_IFNAME`** the same way for PyTorch Gloo.
- **`NCCL_IB_DISABLE=1`** forces NCCL to **not** use IB/RoCE and stay on sockets (matches “no RDMA in container” setups).

### If you want RoCE / IB inside NCCL

1. On the **host**, confirm RDMA devices with **`ibv_devinfo`** / **`ibdev2netdev`** (see `spark1.md` / `spark2.md`).
2. In **Docker**, the container must **see** those devices and userspace (often **`--device /dev/infiniband/`**, caps, sometimes **`--privileged`**, image with **libmlx5** / rdma stack). Without that, logs show **`NET/IB : No device found`** and NCCL falls back to **Socket**.
3. Use **`NCCL_IB_DISABLE=0`**, and set **`NCCL_IB_HCA`** to the intended **HCA** name (from `ibv_devinfo`), consistent with the port wired to the peer.
4. Avoid contradicting settings (for example **`NCCL_IB_DISABLE=1`** together with **`NCCL_IB_HCA=...`** — the disable wins for IB).

Exact Docker flags depend on your image and security policy; start from NVIDIA’s NCCL / RDMA-in-container documentation for your driver and runtime.

---

## Files

| File | Role |
|------|------|
| `verify_dac_link.py` | Connectivity + TCP throughput helper |
| `spark1.md`, `spark2.md` | Captured NIC/RDMA/netplan notes |
