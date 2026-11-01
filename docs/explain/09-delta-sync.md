# 09 · Delta sync: re-upload sends only what changed

**One line:** Re-uploading a file with the same name reuses its UUID and data key, so every unchanged 1 MiB chunk encrypts to exactly the same blob and chunk ID, and we skip chunks that already have 3 live copies.

**Analogy:** A shipping company that stamps each box with a fingerprint of its contents. When you send this week's version of a 20-box shipment and only the last box changed, the warehouse says "I already have 20 of these" and you only ship one box.

## How it works

1. **Same name → same file.** On upload, we look up the latest catalog entry with that name ([transfer.py:106](../../node/transfer.py#L106), [transfer.py:383](../../node/transfer.py#L383)). If one exists, we load its manifest, reuse its `file_uuid`, unwrap its DEK with the KEK, and set `version = old + 1` ([transfer.py:108](../../node/transfer.py#L108)). A new name gets a fresh UUID and a random DEK.
2. **Fixed chunk boundaries.** We read exactly 1 MiB at a time, even if the stream returns short reads ([transfer.py:436](../../node/transfer.py#L436)), so chunk *i* always starts at byte *i* × 1 MiB.
3. **Synthetic nonce.** Each chunk's nonce is `HMAC(nonce_key, flag || plaintext)[:12]`, with `nonce_key = HKDF(DEK)` ([pipeline.py:52](../../node/pipeline.py#L52)). Same key + same AAD (`file_uuid || flag`) + same plaintext → same nonce → byte-identical blob → same chunk ID. See [01](01-pipeline.md).
4. **Skip what's already there.** Before sending a chunk, we count its existing live copies on distinct hosts from the location map ([transfer.py:191](../../node/transfer.py#L191)). Those count toward the 3 copies, and we send only as many new copies as are missing ([transfer.py:196](../../node/transfer.py#L196)). An unchanged chunk with 3 live copies costs zero bytes. An unchanged chunk that lost a copy gets topped up, so a re-upload also acts as a repair.
5. **New manifest, same index slot.** A new manifest (version + 1) is sealed and stored; the catalog entry for that `file_uuid` is replaced, and the owner index is re-published with the new manifest ID in place of the old one ([transfer.py:155](../../node/transfer.py#L155)). The index keeps one manifest per file.
6. **Report it.** The upload result says `sent_bytes`, `sent_chunks` and `reused_chunks` ([transfer.py:176](../../node/transfer.py#L176)), and the dashboard shows them.

## Appends vs insertions

| Change | What gets re-sent |
|---|---|
| Append to a file whose size was an exact multiple of 1 MiB | Only the new chunk(s) |
| Append to a file with a partial last chunk | The old last chunk (it changed) + the new chunk(s) |
| Edit bytes in place (same length) | Only the chunk(s) containing the edit |
| Truncate / shrink | Only the new last chunk, if it became partial |
| Insert or delete bytes near the start | Every chunk after that point, because all boundaries shift |

So delta sync helps logs, CSVs and datasets that grow at the end or are edited in place. Insertions need content-defined chunking (FastCDC), which is (planned).

## What leaks

- **Equality between versions of the same owner's file.** Peers can see which chunk IDs are shared between version 1 and version 2, so they learn *which 1 MiB regions changed*.
- **Equality inside one file.** Two identical 1 MiB chunks in the same file produce the same blob, so peers see they're equal (and store it once).
- **Nothing across files or users.** Each file has its own random DEK, so the same plaintext in two files gives unrelated ciphertext ([test_no_equality_leak_across_files](../../tests/test_pipeline.py#L122)).

## Why this design

**Decision:** reuse the DEK across versions and use a synthetic nonce. See [ARCHITECTURE_DECISIONS.md §14](../ARCHITECTURE_DECISIONS.md#14-delta-sync-re-uploading-a-changed-file-sends-only-the-changed-chunks).

- **Strongest counter:** a deterministic nonce is dangerous with AES-GCM.
- **Our defense:** GCM breaks only when one (key, nonce) pair encrypts *different* plaintexts. Our nonce is a keyed hash of the plaintext, so the same nonce means the same plaintext and the same ciphertext. The only failure is a collision of the 96-bit truncated HMAC, about 2^-48 even with 2^24 chunks under one key. This is the synthetic-IV idea behind SIV (RFC 5297).
- **Second counter:** it leaks equality. **Defense:** yes, within one owner's file, and we say so; across files and users nothing leaks.

The same idea shipped in our production delta OTA pipeline, which sent a 21.6 MB app release as 0.41 MB by sending only changed files. That is a number from that earlier project, not from Minimol.

## Evidence

- [tests/test_pipeline.py](../../tests/test_pipeline.py): [`test_deterministic_for_delta_sync`](../../tests/test_pipeline.py#L106), [`test_append_changes_only_the_tail`](../../tests/test_pipeline.py#L113), [`test_no_equality_leak_across_files`](../../tests/test_pipeline.py#L122).
- [tests/test_transfer.py](../../tests/test_transfer.py): [`test_delta_sync_sends_only_changed_chunks`](../../tests/test_transfer.py#L117), [`test_delta_sync_in_place_edit_and_shrink`](../../tests/test_transfer.py#L130), [`test_index_keeps_one_manifest_per_file`](../../tests/test_transfer.py#L142), [`test_short_reads_keep_fixed_chunk_boundaries`](../../tests/test_transfer.py#L87).
- [tests/test_api_user.py::test_reupload_reports_delta](../../tests/test_api_user.py#L75).
- [tests/test_p1_flow.py::test_upload_recover_on_fresh_laptop_and_delta_sync](../../tests/test_p1_flow.py#L52): with real crypto, a 5-chunk log with appended rows re-sends 1 chunk.

Measured ([bench.py:251](../../bench/bench.py#L251)): Docker cluster, 4 containers on one laptop, real encryption + compression. A 20 MB sensor CSV was uploaded, then ~1% new rows were appended and it was re-uploaded under the same name.

| | Result |
|---|---|
| New version size | 20.2 MB |
| Bytes sent on re-upload | **0.188 MB** (all copies of the one new chunk, after compression) |
| Chunks sent / reused | **1 / 20** |
| Download after re-upload | SHA-256 match |

The first version was exactly 20 MiB, so the append started a new chunk and all 20 old chunks were unchanged. Caveat: one machine, so these prove correctness, not Wi-Fi performance. The multi-laptop run is still to do.

## Limits

- Fixed-size chunks: insertions shift everything after them. FastCDC is (planned).
- "Same file" means same name in this owner's catalog. Renaming a file starts a new file with a new key, and nothing is reused.
- The skip decision uses the location map, which can be up to 10 s stale. A stale map just means re-sending a chunk that's already there, which is harmless (the PUT returns 200).
- Old versions' manifests and chunks stay on peers. There's no history browsing and no garbage collection yet (both planned).
- The manifest itself is always re-sent; it's small and not counted in `sent_bytes`.

## Judge questions

**Q: How can you dedupe encrypted data without the server seeing the content?**
A: The nonce is a keyed hash of the plaintext, so an unchanged chunk encrypts to the same bytes and gets the same ID. Peers never see plaintext; they just see "this ID is already here".
*Follow-up:* "So the peers learn something?" → Yes: which chunks of your file didn't change between versions. Nothing across files or users.

**Q: What happens if I insert a line at the top of the CSV?**
A: Every chunk boundary after it shifts, so every chunk after that point changes and gets re-sent. Delta sync helps appends and in-place edits; insertions need content-defined chunking, which is on our roadmap.
*Follow-up:* "Why not build that now?" → It changes chunk boundaries, manifests and the tests. We picked the version we could finish and measure.

**Q: Is 0.188 MB of 20.2 MB a fair number?**
A: It's the measured blob bytes sent for all copies of the one new chunk, after compression and encryption, with the SHA-256 checked on download. The original file was exactly 20 MiB, which is the best case for an append; a partial last chunk would add one more chunk.
*Follow-up:* "Measured where?" → Docker on one laptop. The bytes-sent number doesn't depend on the network, but timings would.
