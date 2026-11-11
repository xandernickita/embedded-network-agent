# Remote access with Tailscale

Tailscale puts the laptop and the Pi on a private, encrypted network (a "tailnet") that
works across any physical network: home Wi-Fi, campus, a hotspot. Nothing in the agent
changes; it already listens on every interface, and the tunnel is one more interface.

It serves two purposes in this project:

1. **Development and demos away from home.** `nda status` and `nda web` work from anywhere.
2. **A third network path to benchmark.** LAN direct vs. the WireGuard tunnel shows the
   cost of encryption and encapsulation, and the effect of a smaller MTU.

## Setup

**Laptop:** install Tailscale for Windows from tailscale.com/download and sign in.

**Pi (needs to be on the home network the first time):**

```bash
cd ~/embedded-network-agent && git pull && ./deploy/tailscale.sh
```

Open the login URL it prints on the laptop and approve the device. Then, in the Tailscale
admin console, open the `nda-pi` machine and **disable key expiry** (otherwise the Pi
drops off the tailnet after 180 days and needs someone at its console to re-authenticate).

**Check from the laptop:**

```powershell
tailscale ping nda-pi        # "via DERP" = relayed, "via <ip>:<port>" = direct
nda --host nda-pi status
```

## Which name reaches the Pi which way

| Name | Resolves to | Path | Works from |
|---|---|---|---|
| `nda-pi.local` | 192.168.1.x (mDNS) | Home LAN, direct | Home network only |
| `nda-pi` | 100.x.y.z (MagicDNS) | WireGuard tunnel | Anywhere, including at home |

Using `nda-pi` **at home still goes through the tunnel**, just a short one. The name you
type decides the path, so it decides what a benchmark measures.

## Benchmarking rules

- **Primary results use the LAN:** `--host nda-pi.local --link ethernet` (or `wifi`).
- **Tunnel results are labelled:** `--host nda-pi --link tailscale`. `nda bench` warns if
  the address and the label disagree, so rows can't be mislabelled silently.
- **Compare like with like.** For the LAN-vs-tunnel comparison, run both from the same
  place (home) back to back, so the only difference is the tunnel. A run from campus also
  includes the internet between campus and home, which is a different experiment.
- **Record direct vs. relayed** (`tailscale ping nda-pi`) with every tunnel run. If NAT
  traversal fails, traffic goes through a Tailscale DERP relay server and latency includes
  a trip to that server. Campus networks often force this.
- **UDP sizes stop at 1252 bytes over the tunnel.** `tailscale0` has a 1280-byte MTU, so
  the largest unfragmented datagram is 1280 − 20 (IPv4) − 8 (UDP) = 1252. `nda bench`
  caps the matrix at 1252 for `--link tailscale` and rejects larger `--payload` values.
- **`send_errors` is separate from `lost`.** A datagram the OS refuses to send (for example
  over the MTU with Don't-Fragment set) never reached the network, so it isn't counted as
  network loss.

## What to expect (hypotheses to test, not results)

- RTT over the tunnel at home is higher than LAN by the cost of encrypting and
  encapsulating each packet on both ends. On a Pi 3B+ without AES hardware, WireGuard's
  ChaCha20 runs in software, so CPU on the Pi may show it under load.
- Throughput at small payloads should be similar (round-trip bound); at large payloads the
  tunnel adds ~60 bytes of overhead per packet plus encryption cost.
- From campus, latency is dominated by the internet path and whether the connection is
  direct or relayed.

## Security

- Only devices signed in to your tailnet can reach the Pi's 100.x address. The agent has
  no authentication of its own, so **don't share the Pi to other tailnets** or enable a
  Tailscale Funnel for ports 5000/5001.
- The agent's commands are read-only and allowlisted, so a reachable agent can't change
  the Pi; it can only report on it.
- If the laptop is managed by LTU or an employer, check that installing a VPN client is
  allowed before you install Tailscale on it.
