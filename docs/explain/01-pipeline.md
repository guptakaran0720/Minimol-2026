# 01 · Pipeline: chunk, compress, encrypt, hash

**One line:** Each file is cut into 1 MiB pieces, and each piece is compressed (only if that helps), encrypted with AES-256-GCM and named by the SHA-256 of the result.

**Analogy:** Like packing a house move. Every box is packed on its own, vacuum-sealed only if that actually saves space, locked, and labelled with a fingerprint of the locked box. A damaged box is spotted on its own label, without unpacking the whole truck.

## How it works

1. **Chunking.** Upload reads the file exactly 1 MiB at a time ([transfer.py:127](../../node/transfer.py#L127), [read_full at transfer.py:436](../../node/transfer.py#L436)). `CHUNK_SIZE = 1024 * 1024` is fixed in the contract ([contracts.py:14](../../node/contracts.py#L14)). An empty file has 0 chunks, and a file that is an exact multiple of 1 MiB gets no empty trailing chunk. The whole-file SHA-256 is computed as the chunks stream past ([transfer.py:128](../../node/transfer.py#L128)), so the whole file is never in memory; at most 4 chunks are in flight.
2. **Compression, per chunk.** zstd level 3 compresses the chunk ([pipeline.py:72](../../node/pipeline.py#L72)). We keep the compressed form only if it is at least 3% smaller; otherwise we store the chunk raw ([pipeline.py:73](../../node/pipeline.py#L73)). This decision is made for every chunk, so a file that mixes text and JPEG data is handled correctly.
3. **Synthetic nonce.** The 12-byte nonce is `HMAC-SHA256(nonce_key, flag || plaintext)[:12]` ([pipeline.py:56](../../node/pipeline.py#L56)). The `nonce_key` is `HKDF-SHA256(DEK, info="minimol-2026/nonce/v1")` ([pipeline.py:52](../../node/pipeline.py#L52)), so the file's data key (DEK) itself is used only for AES-GCM. Same plaintext + same key → same nonce → same ciphertext. That is what makes delta sync work ([09](09-delta-sync.md)).
4. **Encryption.** AES-256-GCM with the file's DEK. The authenticated-but-not-encrypted data (AAD) is `file_uuid || flag` ([pipeline.py:60](../../node/pipeline.py#L60)). The stored blob is `nonce || ciphertext || tag` ([pipeline.py:79](../../node/pipeline.py#L79)), which adds 28 bytes per chunk ([pipeline.py:36](../../node/pipeline.py#L36)).
5. **Hashing.** The chunk ID is `SHA-256(blob)` ([pipeline.py:82](../../node/pipeline.py#L82)). Peers check this hash on every PUT, and the downloader re-checks it on every GET.
6. **Decoding, in order of checks** ([pipeline.py:89](../../node/pipeline.py#L89)): blob length is in range (line 93); the GCM tag verifies (line 98); the zstd frame declares a size between 1 byte and 1 MiB, before any decompression (lines 106–110); decompression is capped at 1 MiB with `max_output_size` (line 112); the output matches the declared size (line 115); and finally the nonce must equal the one recomputed from the decoded plaintext (line 120). Any failure raises `DecodeError`, and callers treat that copy as corrupt.

The decompression-bomb check matters: python-zstandard ignores `max_output_size` when the frame header declares its own content size, so we read the declared size first and refuse anything over 1 MiB ([pipeline.py:103](../../node/pipeline.py#L103)). Frames without a declared size are refused.

## Why this design

**Decision:** process each chunk separately (compress, then encrypt), instead of compressing and encrypting the whole file and then splitting it. See [ARCHITECTURE_DECISIONS.md §3](../ARCHITECTURE_DECISIONS.md#3-pipeline-process-each-chunk-separately-not-the-whole-file).

- **Strongest counter:** compressing chunks separately gives a slightly worse ratio, and every chunk pays 28 bytes of overhead.
- **Our defense:** zstd level 3 only looks back a few MB, so the loss is small, and we measure it rather than guess (`measure_compression` at [pipeline.py:125](../../node/pipeline.py#L125) reports whole-file vs per-chunk ratios). In return we get: an integrity check on every chunk, memory bounded to a few chunks, a hard 1 MiB decompression cap, and a per-chunk compress-or-not decision.

**Decision:** chunk ID = SHA-256 of the *ciphertext*, and a random UUID for the file ID. See [§4](../ARCHITECTURE_DECISIONS.md#4-chunk-id--sha-256-of-the-encrypted-blob).

- **Counter:** no deduplication across users.
- **Defense:** cross-user deduplication (convergent encryption) lets anyone confirm whether a known file is stored. We accept the lost dedup. The plaintext SHA-256 lives only inside the encrypted manifest.

**Decision:** a deterministic (synthetic) nonce. See [§14](../ARCHITECTURE_DECISIONS.md#14-delta-sync-re-uploading-a-changed-file-sends-only-the-changed-chunks).

- **Counter:** reusing a nonce with AES-GCM is catastrophic.
- **Defense:** GCM breaks when one (key, nonce) pair encrypts *different* plaintexts. Our nonce is derived from the plaintext under a secret key, so the same nonce means the same plaintext and the same ciphertext. The only failure mode is a collision of the 96-bit truncation, which is negligible at our scale. This is the synthetic-IV idea behind SIV (RFC 5297).

## Evidence

Tests in [tests/test_pipeline.py](../../tests/test_pipeline.py), all on the real code:

- `test_round_trip_random`, `test_round_trip_compressible`: encode → decode gives the original bytes.
- `test_empty_file_has_no_chunks`, `test_exact_multiple_has_no_trailing_chunk`.
- [`test_random_data_stored_raw`](../../tests/test_pipeline.py#L84): random data is stored raw, blob = 1 MiB + 28 bytes.
- [`test_mixed_file_decided_per_chunk`](../../tests/test_pipeline.py#L90): text, random, text → compressed, raw, compressed.
- [`test_compression_kept_only_if_it_saves_3_percent`](../../tests/test_pipeline.py#L95).
- [`test_deterministic_for_delta_sync`](../../tests/test_pipeline.py#L106) and [`test_no_equality_leak_across_files`](../../tests/test_pipeline.py#L122).
- [`test_tampered_blob_rejected`](../../tests/test_pipeline.py#L133), [`test_wrong_key_file_or_flag_rejected`](../../tests/test_pipeline.py#L142).
- [`test_decompression_bomb_rejected`](../../tests/test_pipeline.py#L168): a <10 KB frame declaring 50 MiB is refused. Also `test_frame_without_content_size_rejected` and [`test_nonce_must_match_plaintext`](../../tests/test_pipeline.py#L183).
- [tests/test_p1_flow.py::test_upload_recover_on_fresh_laptop_and_delta_sync](../../tests/test_p1_flow.py#L52): the full P1 flow with real crypto.

Measured (Docker cluster, 4 containers on one laptop, real encryption + compression, 5 reps, medians):

- 20 MB sensor CSV: encoded / original = **0.302**. Stored across 3 copies / original = **0.905**, so compression paid for almost all of the 3× replication.
- 5 MB random bytes: ratio **1.000** (every chunk stored raw), stored / original **3.0**.
- Downloaded bytes matched the original SHA-256 in every rep.

Caveat: one machine, so these prove correctness, not Wi-Fi performance. The multi-laptop run is still to do.

## Limits

- Fixed-size chunks. An insertion near the start shifts every later chunk. Content-defined chunking (FastCDC) is (planned).
- The compression ratio of a chunk is visible to peers through its blob size. We don't pad.
- One zstd level (3). No dictionary training.
- No deduplication across files or users, by design.
- We have not published a measured per-chunk vs whole-file comparison yet; `python -m node.pipeline FILE` prints it.

## Judge questions

**Q: Why compress before encrypting and not after?**
A: Good ciphertext looks random, so it doesn't compress at all. Compression has to come first, and that is also what the brief asks for: compression on the client.
*Follow-up:* "Doesn't compress-then-encrypt leak information, like CRIME?" → Size can leak compressibility; an attacker would need to inject chosen data into your file and watch sizes. That doesn't fit our threat model, but we name it.

**Q: Isn't a deterministic nonce a textbook AES-GCM mistake?**
A: Reusing a nonce for *different* plaintexts is the mistake. Our nonce is a keyed hash of the plaintext, so a repeated nonce always comes with identical plaintext and identical ciphertext, which is the SIV construction.
*Follow-up:* "Then what does it leak?" → That two chunks of the same file are equal. Nothing across files, because each file has its own key.

**Q: What stops a malicious peer from sending a zip bomb?**
A: Before decompressing, we read the size the zstd frame declares and refuse anything over 1 MiB; then decompression itself is capped at 1 MiB. A frame with no declared size is refused.
*Follow-up:* "Could it get past the GCM tag?" → No. It would need the file's key to produce a valid tag, so a random peer can't even reach the decompressor.
