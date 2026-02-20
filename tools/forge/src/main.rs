use rand::RngCore;
use secp256k1::{PublicKey, Secp256k1, SecretKey};
use serde::Serialize;
use std::env;
use std::sync::{
    atomic::{AtomicBool, AtomicU64, Ordering},
    Arc, Mutex,
};
use std::thread;
use std::time::{Duration, Instant};
use tiny_keccak::{Hasher, Keccak};

#[derive(Clone, Debug)]
struct Opts {
    prefix: String,
    threads: usize,
    json: bool,
}

#[derive(Serialize)]
struct ProgressMsg {
    r#type: &'static str,
    candidates: u64,
    elapsed_ms: u128,
    rate: u64,
}

#[derive(Serialize, Clone)]
struct FoundMsg {
    r#type: &'static str,
    address: String,
    private_key: String,
    public_key: String,
    candidates: u64,
    elapsed_ms: u128,
}

fn parse_args() -> Opts {
    let mut prefix = "b1e55ed".to_string();
    let mut threads = std::thread::available_parallelism().map(|n| n.get()).unwrap_or(4);
    let mut json = false;

    let mut it = env::args().skip(1);
    while let Some(arg) = it.next() {
        match arg.as_str() {
            "--prefix" => {
                if let Some(v) = it.next() {
                    prefix = v;
                }
            }
            "--threads" => {
                if let Some(v) = it.next() {
                    if let Ok(n) = v.parse::<usize>() {
                        if n > 0 {
                            threads = n;
                        }
                    }
                }
            }
            "--json" => {
                json = true;
            }
            "-h" | "--help" => {
                eprintln!(
                    "b1e55ed-forge --prefix <hex> --threads <N> [--json]\n\nStreams JSON lines to stdout."
                );
                std::process::exit(0);
            }
            _ => {}
        }
    }

    Opts {
        prefix,
        threads,
        json,
    }
}

fn keccak256(data: &[u8]) -> [u8; 32] {
    let mut k = Keccak::v256();
    let mut out = [0u8; 32];
    k.update(data);
    k.finalize(&mut out);
    out
}

fn eth_address_from_pubkey(pk: &PublicKey) -> [u8; 20] {
    // Ethereum address = last 20 bytes of keccak256(uncompressed_pubkey[1..])
    let uncompressed = pk.serialize_uncompressed();
    let hash = keccak256(&uncompressed[1..]);
    let mut out = [0u8; 20];
    out.copy_from_slice(&hash[12..]);
    out
}

fn main() {
    let opts = parse_args();
    // We always stream JSON; --json exists for CLI compatibility.
    let _ = opts.json;

    let prefix_lower = opts.prefix.to_lowercase();

    let secp = Secp256k1::new();

    let start = Instant::now();
    let candidates = Arc::new(AtomicU64::new(0));
    let found_flag = Arc::new(AtomicBool::new(false));
    let result: Arc<Mutex<Option<FoundMsg>>> = Arc::new(Mutex::new(None));

    // Progress reporter
    {
        let candidates = Arc::clone(&candidates);
        let found_flag = Arc::clone(&found_flag);
        thread::spawn(move || {
            let mut last = 0u64;
            loop {
                thread::sleep(Duration::from_secs(1));
                let c = candidates.load(Ordering::Relaxed);
                let elapsed_ms = start.elapsed().as_millis();
                let rate = c.saturating_sub(last);
                last = c;
                let msg = ProgressMsg {
                    r#type: "progress",
                    candidates: c,
                    elapsed_ms,
                    rate,
                };
                println!("{}", serde_json::to_string(&msg).unwrap());
                if found_flag.load(Ordering::Relaxed) {
                    break;
                }
            }
        });
    }

    let mut handles = Vec::new();
    for _ in 0..opts.threads {
        let candidates = Arc::clone(&candidates);
        let found_flag = Arc::clone(&found_flag);
        let result = Arc::clone(&result);
        let secp = secp.clone();
        let prefix_lower = prefix_lower.clone();

        let h = thread::spawn(move || {
            let mut rng = rand::thread_rng();
            let mut sk_bytes = [0u8; 32];
            loop {
                if found_flag.load(Ordering::Relaxed) {
                    return;
                }

                rng.fill_bytes(&mut sk_bytes);
                let sk = match SecretKey::from_slice(&sk_bytes) {
                    Ok(v) => v,
                    Err(_) => continue,
                };
                let pk = PublicKey::from_secret_key(&secp, &sk);
                let addr_bytes = eth_address_from_pubkey(&pk);
                let addr_hex = hex::encode(addr_bytes);

                let c = candidates.fetch_add(1, Ordering::Relaxed) + 1;

                if addr_hex.starts_with(&prefix_lower) {
                    // Winner takes all. First thread to flip the flag stores the result.
                    let won = found_flag
                        .compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
                        .is_ok();
                    if won {
                        let elapsed_ms = start.elapsed().as_millis();
                        let found = FoundMsg {
                            r#type: "found",
                            address: format!("0x{}", addr_hex),
                            private_key: format!("0x{}", hex::encode(sk.secret_bytes())),
                            public_key: format!("0x{}", hex::encode(pk.serialize_uncompressed())),
                            candidates: c,
                            elapsed_ms,
                        };
                        *result.lock().unwrap() = Some(found);
                    }
                    return;
                }
            }
        });
        handles.push(h);
    }

    for h in handles {
        let _ = h.join();
    }

    if let Some(found) = result.lock().unwrap().clone() {
        println!("{}", serde_json::to_string(&found).unwrap());
        std::process::exit(0);
    }

    // Should never happen in practice.
    eprintln!("{}", serde_json::to_string(&serde_json::json!({"type":"error","message":"no result"})).unwrap());
    std::process::exit(1);
}
