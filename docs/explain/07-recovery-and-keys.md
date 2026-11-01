# 07 · Keys and recovery on a fresh device

**One line:** Your username and passphrase deterministically produce your keys, so any node in the cluster can rebuild your whole file list from a signed, encrypted index that peers keep for you.

**Analogy:** Your passphrase is a recipe for a key, not a key you carry around. Any locksmith in town can follow the recipe and cut the same key. The peers keep a locked, signed list of your boxes, so on a new laptop you cut the key, open the list, and find every box.

## How it works

1. **Salt from the username.** `owner_salt(username) = SHA-256("minimol-2026/owner-salt/v1|" + username)` ([contracts.py:18](../../node/contracts.py#L18)). It's fixed by contract, so a fresh laptop needs no stored salt file. The username keeps two people with the same passphrase from getting the same keys.
2. **scrypt → master secret.** The passphrase must be at least 12 characters ([keys.py:64](../../node/keys.py#L64)). It is Unicode-normalised (NFKC) so it gives the same bytes on macOS, Windows and Linux ([keys.py:69](../../node/keys.py#L69)), then stretched with scrypt n = 2^17, r = 8, p = 1, which uses 128 MiB of RAM per attempt ([keys.py:33](../../node/keys.py#L33), [keys.py:70](../../node/keys.py#L70)).
3. **Two keys from the master** via HKDF with different labels ([keys.py:72](../../node/keys.py#L72)):
   - **KEK** (key-encryption key): wraps each file's data key, and encrypts manifests and the index.
   - **Ed25519 signing key**: signs the owner index. Its public key is the owner's ID on the peers.
4. **Per-file data key (DEK), wrapped.** Each new file gets a random 256-bit DEK and a random UUID ([transfer.py:112](../../node/transfer.py#L112)). The DEK is encrypted under the KEK with AES-GCM (`wrap_key`, [keys.py:91](../../node/keys.py#L91)) and stored inside the file's manifest. The manifest, which also holds the name, size, plaintext SHA-256 and ordered chunk list, is itself AES-GCM-encrypted under the KEK ([manifest.py:80](../../node/manifest.py#L80)) and stored on 3 peers like a chunk.
5. **Signed owner index.** After each upload, the node seals the list of manifest IDs (one per file, the latest version) with `version + 1`: the list is encrypted under the KEK with `owner_pub + version` as AAD, and Ed25519 signs `owner_pub || version || sha256(blob)` ([index.py:51](../../node/index.py#L51)). It's pushed to **every** alive peer ([transfer.py:331](../../node/transfer.py#L331)). Each peer verifies the signature before storing, needs no secret to do so, and keeps only the highest version, answering 409 to anything older ([api_peer.py:173](../../node/api_peer.py#L173), [chunkstore.py:118](../../node/chunkstore.py#L118)).
6. **Fresh-device recovery.** `POST /recover {username, passphrase}` on any node ([api_user.py:127](../../node/api_user.py#L127)):
   - re-derives the keys,
   - asks every alive peer for the index at `owner_pub` ([transfer.py:347](../../node/transfer.py#L347)),
   - drops records that fail the signature check and keeps the highest valid version ([transfer.py:357](../../node/transfer.py#L357)),
   - decrypts the manifest-ID list, fetches and opens each manifest, and rebuilds the local catalog ([transfer.py:364](../../node/transfer.py#L364)).

   The same call is "log in on my laptop" and "recover on a new laptop". Until it succeeds, the `/files` routes answer 401; `/stats` works while locked so the dashboard can show peers.

## Why this design

**Decision:** keys come from a passphrase, not a key file on one laptop. See [ARCHITECTURE_DECISIONS.md §5](../ARCHITECTURE_DECISIONS.md#5-keys-come-from-a-passphrase-not-a-key-file-on-one-laptop).

- **Strongest counter:** a weak passphrase can be guessed offline by anyone holding the encrypted manifests or index.
- **Our defense:** scrypt at 128 MiB per guess makes each guess expensive, we require at least 12 characters, and only cluster members can fetch manifests and index records at all. Without this design, if the uploader's laptop died, every file would be lost even though every chunk had 3 copies, which would make the redundancy claim false.

**Decision:** an immutable manifest per version, plus one signed, versioned index per owner. See [§7](../ARCHITECTURE_DECISIONS.md#7-chunk-locations-are-soft-state-and-manifests-never-change).

- **Counter:** a peer could hand back an older index (rollback).
- **Defense:** a peer can't forge or raise the version, because the version is inside the signature. It can only withhold the newest one. We ask every peer and take the highest valid version, so rollback needs every peer to cooperate.

## Evidence

- [tests/test_keys.py](../../tests/test_keys.py): `test_same_inputs_same_keys`, [`test_username_separates_users`](../../tests/test_keys.py#L24), `test_passphrase_changes_keys`, [`test_unicode_normalisation`](../../tests/test_keys.py#L36), `test_short_passphrase_rejected`, [`test_unwrap_rejects_wrong_kek_and_tampering`](../../tests/test_keys.py#L70), [`test_production_scrypt_cost_is_used_by_default`](../../tests/test_keys.py#L87).
- [tests/test_index.py](../../tests/test_index.py): [`test_fresh_laptop_reads_index`](../../tests/test_index.py#L45), `test_other_owner_rejected`, `test_tampered_record_rejected`, [`test_version_cannot_be_raised_by_a_peer`](../../tests/test_index.py#L69), [`test_rollback_defence_picks_highest_valid`](../../tests/test_index.py#L89).
- [tests/test_manifest.py](../../tests/test_manifest.py): `test_dek_survives_round_trip`, `test_blob_hides_contents`, `test_wrong_kek_and_tampering_rejected`, `test_large_file_manifest_fits_one_chunk`.
- [tests/test_transfer.py](../../tests/test_transfer.py): [`test_recover_on_fresh_device_with_username_and_passphrase`](../../tests/test_transfer.py#L240), [`test_recover_ignores_forged_index_wrong_passphrase_and_other_user`](../../tests/test_transfer.py#L254).
- [tests/test_api_user.py::test_fresh_device_recovers_and_downloads](../../tests/test_api_user.py#L98) and `test_locked_until_recover`.
- [tests/test_p1_flow.py::test_upload_recover_on_fresh_laptop_and_delta_sync](../../tests/test_p1_flow.py#L52): the whole flow with real crypto.
- Live: [tests/test_cluster.py](../../tests/test_cluster.py#L46) step 7 recovers the file list on a *different* node from username + passphrase alone and downloads with a matching SHA-256. It passed against the Docker cluster and against `scripts/run_cluster.sh`. Caveat: one machine, so this proves correctness, not Wi-Fi performance; the multi-laptop run is still to do.

## Limits

- **Forget the passphrase, lose the data.** There is no reset and no escrow, by design.
- The salt comes from the username, which isn't secret. An attacker could precompute guesses for one known username. scrypt cost is the only defense.
- **One writer at a time.** Two devices uploading for the same owner at once both pick "version + 1"; peers reject the lower one with 409, so that device's new file is missing from the index until a later publish from it wins. A CRDT merge is (planned).
- A peer that was offline during an upload misses that index version. Recovery asks every alive peer, so this only matters if *only* stale peers are reachable.
- Recovery loads every manifest. If any one manifest is unavailable, `/recover` fails as a whole rather than restoring the rest.
- Unlocking is per process: after a restart the node is locked again until `/recover`. The local catalog file is just a cache; the index on peers is the durable copy.
- No key rotation and no passphrase change (planned).

## Judge questions

**Q: My laptop is stolen. What do I need to get my files back?**
A: Only your username and passphrase, typed into any node in the cluster. It re-derives the same keys, pulls your signed index from the peers, and lists every file, which is demo step 7.
*Follow-up:* "And the thief?" → The laptop holds only ciphertext and no stored key. Unless they know your passphrase, they're stuck guessing at 128 MiB of scrypt per guess.

**Q: Can a malicious peer give me an old file list?**
A: It can withhold the newest version but can't forge one, because the version number is inside the Ed25519 signature. We ask every peer and take the highest valid version.
*Follow-up:* "What if every peer is malicious?" → Then rollback works, and we say so. Closed membership is what makes that unlikely.

**Q: Why scrypt and not just SHA-256 of the passphrase?**
A: SHA-256 is fast, so an attacker could try billions of guesses per second. scrypt with these settings costs 128 MiB of memory and a noticeable fraction of a second per guess, which makes GPU-scale guessing expensive.
*Follow-up:* "Why not Argon2?" → Argon2id would also be a good choice; scrypt is in the `cryptography` library we already use, so it cost no new dependency.
