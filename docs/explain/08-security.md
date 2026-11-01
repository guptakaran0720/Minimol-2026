# 08 · Security: what we protect, and what we don't

**One line:** Data is encrypted and authenticated on the owner's machine before it leaves; peers authenticate each other with a shared cluster key; and the user API only answers this machine.

**Analogy:** Your valuables go into a locked, tamper-evident safe before they leave your house, so the courier and the warehouse can lose the safe but can't open it or swap its contents without you noticing. The warehouse also has a members-only door (the cluster key). What the lock can't hide is how big the safe is and when you sent it.

## How it works

1. **Client-side encryption.** Every chunk is AES-256-GCM-encrypted with a per-file key before upload ([pipeline.py:79](../../node/pipeline.py#L79)). Manifests and the owner index are encrypted under the owner's KEK ([manifest.py:80](../../node/manifest.py#L80), [index.py:51](../../node/index.py#L51)). Peers only ever hold ciphertext. Keys never leave the owner's node.
2. **Three integrity checks on every download:** the blob's SHA-256 must equal the chunk ID ([transfer.py:318](../../node/transfer.py#L318)); the GCM tag must verify, with `file_uuid || flag` as AAD ([pipeline.py:98](../../node/pipeline.py#L98)); and the whole file's SHA-256 must match the manifest before the file is served ([transfer.py:259](../../node/transfer.py#L259)).
3. **Peer authentication.** Every peer request is HMAC-signed over `method|path|node_id|ts|sha256(body)` and accepted within ±30 s ([auth.py:23](../../node/auth.py#L23)). Every answer is signed back, bound to the request's signature ([auth.py:53](../../node/auth.py#L53)), and the client rejects unsigned answers or answers from the wrong node ([peer_client.py:40](../../node/peer_client.py#L40)).
4. **Resource limits.** Disk quota → 507 ([chunkstore.py:64](../../node/chunkstore.py#L64)). Body caps while streaming: chunk 1 MiB + 64 B, index 1 MiB ([api_peer.py:71](../../node/api_peer.py#L71)), upload 256 MiB ([api_user.py:40](../../node/api_user.py#L40)) → 413. No peer DELETE route.
5. **User API, this machine only.** The user API shares the node's port with the peer API, so it is reachable on the network. Every user route runs a check on the caller's IP and answers **403** unless it is `127.0.0.1`, `::1` or inside `USER_API_ALLOW` ([main.py:88](../../node/main.py#L88), [config.py:109](../../node/config.py#L109), and again in [api_user.py:111](../../node/api_user.py#L111)). `USER_API_ALLOW` exists only for Docker: published ports arrive from the bridge gateway, so [compose.yaml](../../compose.yaml) allows exactly the two gateway addresses and binds the published ports to the host's `127.0.0.1`. Never set it to a LAN range on real laptops ([DOCKER.md](../DOCKER.md)).
6. **Owner index signatures.** Peers verify the Ed25519 signature on every `PUT /index` and keep only the highest version ([api_peer.py:183](../../node/api_peer.py#L183)).

## Threat table (as implemented)

Updated from [ARCHITECTURE_DECISIONS.md §12](../ARCHITECTURE_DECISIONS.md#12-security-cluster-hmac-quotas-no-remote-delete) to match the code.

| Threat | Mitigation in the code | Status |
|---|---|---|
| Peer returns a corrupted or fake chunk | SHA-256 vs chunk ID, then GCM tag, then whole-file SHA-256; bad peer goes suspect + 15 s cooldown | Done |
| Unauthorized node joins | Cluster HMAC on every request; a candidate becomes a peer only after an authenticated heartbeat | Done |
| Stranger answers as a peer (fake `/health`, fake `HEAD 200`) | Signed responses bound to the request signature and the expected node_id | Done |
| Request relabelled as another node | `node_id` is inside the request HMAC | Done |
| Disk exhaustion or huge upload | Quota (507), streaming body caps (413) | Done |
| Decompression bomb | Declared zstd size checked first, then `max_output_size = 1 MiB` | Done |
| Index tampering or rollback | Ed25519 signature; peers keep the highest version; recovery takes the highest valid version across all peers | Done (rollback only reduced) |
| Peer claims to store data it deleted | Every 5 s each node challenges another holder of a chunk it also holds with a fresh random nonce (`POST /audit/{id}`); the holder must return HMAC-SHA256(nonce, chunk bytes), which needs the exact bytes. A failed audit distrusts that copy for 120 s, so repair restores a real copy elsewhere (or replaces the rotten one in place); `HEAD` around each repair PUT; every download re-hashes | MVP; relaying challenges isn't stopped |
| Fake free-space claims | A refused PUT moves on to the next peer and marks the refuser suspect; only confirmed copies count | Done |
| Replay within 30 s | Only idempotent requests are affected (re-PUT, re-read ciphertext) | Accepted |
| Sybil attack | Closed membership via the cluster key | Done for a closed cluster, not open-network safe |
| Traffic sniffing | Payloads are ciphertext; headers, sizes and timing are visible; TLS is (planned) | Partial |
| Someone on the LAN uses my user API | Per-request client-IP check (403); Docker ports bound to 127.0.0.1 | Done |
| Leaked cluster key | Attacker can join, store junk up to quotas, read ciphertext. Can't decrypt, can't forge an index | Accepted; mTLS per node is (planned) |

## What AES-GCM protects, and what it doesn't

**It protects:**
- **Confidentiality** of chunk contents, file names, sizes inside manifests, and the file list.
- **Integrity**: any change to a blob makes the tag fail.
- **Binding to a file**: the AAD contains the file's UUID, so a chunk can't be moved into a different file. Order within a file is protected by the ordered chunk list in the encrypted manifest.

**It does not protect:**
- **Availability.** A peer can delete or withhold what it stores. That is what 3 copies and repair are for.
- **Metadata.** Peers see blob sizes (and so roughly how compressible each chunk is), how many chunks there are, when uploads happen, which node sent them, and the owner's public key on the index.
- **Equality within one file's versions.** Synthetic nonces make unchanged chunks identical across versions (doc 09). Nothing leaks across files or users.
- **A compromised owner machine or a guessed passphrase.** If either falls, everything that owner stored is readable.
- **The user API itself.** There's no login token on it; it trusts any process on the same machine once the node is unlocked.

## Why this design

**Decision:** one cluster HMAC key, plus client-side encryption. See [§12](../ARCHITECTURE_DECISIONS.md#12-security-cluster-hmac-quotas-no-remote-delete).

- **Strongest counter:** one leaked laptop exposes the shared key.
- **Our defense:** the key only controls who may talk to the cluster. It can't decrypt anything, because file keys come from each owner's passphrase. Per-node identities with mutual TLS are the right next step, and we label it planned.

## Evidence

- [tests/test_auth.py](../../tests/test_auth.py): `test_any_change_rejected`, `test_timestamp_window`, `test_missing_headers_rejected`, `test_response_signature`.
- [tests/test_api_peer.py](../../tests/test_api_peer.py): `test_hmac_rejection`, `test_status_codes`, [`test_unsigned_or_impostor_responses_rejected`](../../tests/test_api_peer.py#L161), [`test_replayed_response_rejected`](../../tests/test_api_peer.py#L183).
- [tests/test_pipeline.py](../../tests/test_pipeline.py): `test_tampered_blob_rejected`, `test_wrong_key_file_or_flag_rejected`, `test_decompression_bomb_rejected`, `test_no_equality_leak_across_files`.
- [tests/test_index.py](../../tests/test_index.py): `test_tampered_record_rejected`, `test_version_cannot_be_raised_by_a_peer`, `test_rollback_defence_picks_highest_valid`.
- User API locality: [tests/test_main_ui.py::test_user_api_rejects_non_local_clients](../../tests/test_main_ui.py#L44), `test_user_api_client_ok`, and [tests/test_api_user.py::test_rejects_requests_from_other_machines](../../tests/test_api_user.py#L42).
- [tests/test_transfer.py](../../tests/test_transfer.py): `test_corrupt_holder_is_skipped_and_penalised`, `test_whole_file_hash_mismatch_raises`, `test_recover_ignores_forged_index_wrong_passphrase_and_other_user`.

## Limits

- Not open-network safe: anyone with the cluster key is trusted as a member.
- Plain HTTP between nodes; TLS is (planned).
- Audits can't stop a peer from relaying a challenge to an honest holder and passing on its answer; that needs per-node identities (planned).
- No per-user quotas; the quota is per node.
- We haven't had an external security review. These are our own tests.

## Judge questions

**Q: Can the other laptops read my files?**
A: No. Everything is encrypted with AES-256-GCM on your machine before it leaves, using a key that only your passphrase can unlock. Peers store and serve ciphertext they can't decrypt.
*Follow-up:* "What can they learn?" → Sizes, timing, how many chunks, and which chunks stayed the same between versions of one of your files. We say that openly.

**Q: Your user API has no password. Can't anyone on the Wi-Fi upload or download?**
A: Every user route checks the caller's IP and returns 403 unless it's localhost; the only exception is the Docker gateway address, and Docker's ports are bound to 127.0.0.1. So only processes on that machine can use it.
*Follow-up:* "And malware on the same machine?" → It could use the unlocked API. We don't defend against a compromised owner machine.

**Q: What does the cluster key protect if it's shared by everyone?**
A: Membership: strangers can't join, write to disks, or impersonate a node, because requests and responses are both signed. It doesn't protect file contents; that's the job of the per-owner keys.
*Follow-up:* "What if it leaks?" → An attacker could join and waste quota or withhold data, but not read or forge files. Per-node mTLS is our planned fix.
