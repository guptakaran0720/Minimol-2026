# Glossary

Plain-English meanings of the words we use on stage. One line each.

| Term | Meaning |
|---|---|
| **Node** | One running copy of our Python program; a laptop or a Docker container. |
| **Host / `host_id`** | The physical machine a node runs on; we never put two copies of a chunk on the same host. |
| **Cluster key** | A shared secret every node knows; it proves "I'm one of us" but can't decrypt anyone's files. |
| **Chunk** | A 1 MiB piece of a file; the last piece of a file can be smaller. |
| **Blob** | A chunk after compression and encryption: nonce + ciphertext + 16-byte tag. |
| **Chunk ID** | The SHA-256 fingerprint of a blob; it's both the chunk's name and its integrity check. |
| **zstd** | A fast compression algorithm; we use level 3 and keep the result only if it saves at least 3%. |
| **AES-256-GCM** | The encryption we use; it hides the data and also detects any change to it. |
| **GCM tag** | The 16-byte check value AES-GCM adds; if a single bit of the blob changes, decryption fails. |
| **AAD** | Extra data that encryption vouches for without hiding; we use the file's UUID so a chunk can't be moved to another file. |
| **Nonce** | A 12-byte "number used once" that AES-GCM needs for each encryption. |
| **Synthetic nonce** | A nonce computed as a keyed hash of the chunk's content, so unchanged chunks encrypt identically (the SIV idea). |
| **DEK** | Data encryption key: a random key per file that encrypts its chunks. |
| **KEK** | Key encryption key: derived from your passphrase; it encrypts every DEK, every manifest, and your file list. |
| **scrypt** | A deliberately slow, memory-hungry function that turns a passphrase into a key, so guessing is expensive. |
| **Ed25519** | A digital signature scheme; we use it to sign your file list so peers can check it's really yours. |
| **Manifest** | A file's encrypted recipe: name, size, hash, wrapped DEK, and the ordered list of chunk IDs. |
| **Owner index** | Your signed, encrypted list of manifests (one per file), stored on every peer under your public key. |
| **Replication factor (R = 3)** | Every chunk is kept as 3 full copies on 3 different hosts. |
| **Rendezvous hashing** | A way for every node to rank peers for a chunk identically, with no coordinator; ours is weighted and has a slow tier. |
| **Tier 2 (slow tier)** | Peers measured as much slower than the rest for 30 s; they get no new chunks until they recover. |
| **ETA** | Estimated time to fetch a chunk from a peer: round-trip time plus size divided by measured bandwidth. |
| **EWMA** | A running average that weights recent measurements more (ours gives each new sample 30%). |
| **Hedged read** | If the first peer is slow to answer, also ask the next one and use whichever verified reply comes first. |
| **Heartbeat** | A signed `/health` ping every 2 s that tells us a peer is still there. |
| **Suspect / dead** | Suspect: missed 2 heartbeats or failed a transfer; dead: no contact for 20 s, which triggers repair. |
| **Location map** | Each node's in-memory list of which peers hold which chunks, rebuilt from `/inventory` every 10 s. |
| **Repair leader** | The one holder of a chunk that all holders agree should copy it when a copy is lost. |
| **Degraded / unavailable** | Degraded: some chunk has fewer than 3 live copies; unavailable: some chunk has no live copy. |
| **Delta sync** | Re-uploading a changed file sends only the chunks that changed. |
