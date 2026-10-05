//! Reference Rust implementation of the UFCS-FQL/1 sender/receiver pair.
//! Standard library only (CRC32 is computed here), wire-compatible with the
//! PHP and Go lab nodes.
//!
//!   cargo run --release -- recv 9100
//!   cargo run --release -- send 127.0.0.1 9100 ../../data/ufcs_sample.jsonl 100
//!
//! Payloads are sent uncompressed (CompressionType NONE); the receiver
//! verifies CRC32, acknowledges every ACK_REQUESTED frame and reports counts.
//! It does not decompress or re-validate fingerprints — the PHP and Go nodes do.

use std::io::{BufReader, Read, Write};
use std::net::{TcpListener, TcpStream};
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::Arc;
use std::{env, fs, thread, time::Duration};

const MAGIC: u16 = 0xF051;
const VERSION: u8 = 1;
const FACT_BATCH: u8 = 0;
const CONTROL: u8 = 2;
const F_SIGNED: u16 = 0x0008;
const F_ACK_REQUESTED: u16 = 0x0020;
const PRIORITY_FLAGS: [u16; 3] = [0x0001, 0x0002, 0x0004];
const ROLES: [&str; 3] = ["control", "normal", "bulk"];

#[derive(Debug, Default, Clone)]
struct FrameHeader {
    magic: u16,
    version: u8,
    msg_type: u8,
    content_type: u8,
    compression_type: u8,
    flags: u16,
    payload_len: u32,
    meta_len: u32,
    message_id: u64,
    sequence: u32,
    reserved: u32,
}

struct Frame {
    header: FrameHeader,
    meta: Vec<u8>,
    payload: Vec<u8>,
    crc32: u32,
}

fn crc32(data: &[u8]) -> u32 {
    let mut crc = 0xFFFF_FFFFu32;
    for &b in data {
        crc ^= b as u32;
        for _ in 0..8 {
            crc = if crc & 1 != 0 { (crc >> 1) ^ 0xEDB8_8320 } else { crc >> 1 };
        }
    }
    !crc
}

fn encode(frame: &mut Frame) -> Vec<u8> {
    let h = &mut frame.header;
    h.magic = MAGIC;
    h.version = VERSION;
    h.meta_len = frame.meta.len() as u32;
    h.payload_len = frame.payload.len() as u32;
    h.flags &= !F_SIGNED;
    let mut buf = Vec::with_capacity(36 + frame.meta.len() + frame.payload.len());
    buf.extend_from_slice(&h.magic.to_be_bytes());
    buf.push(h.version);
    buf.push(h.msg_type);
    buf.push(h.content_type);
    buf.push(h.compression_type);
    buf.extend_from_slice(&h.flags.to_be_bytes());
    buf.extend_from_slice(&h.payload_len.to_be_bytes());
    buf.extend_from_slice(&h.meta_len.to_be_bytes());
    buf.extend_from_slice(&h.message_id.to_be_bytes());
    buf.extend_from_slice(&h.sequence.to_be_bytes());
    buf.extend_from_slice(&h.reserved.to_be_bytes());
    buf.extend_from_slice(&frame.meta);
    buf.extend_from_slice(&frame.payload);
    frame.crc32 = crc32(&buf);
    buf.extend_from_slice(&frame.crc32.to_be_bytes());
    buf
}

fn read_frame<R: Read>(r: &mut R) -> std::io::Result<Frame> {
    let mut hb = [0u8; 32];
    r.read_exact(&mut hb)?;
    let u16at = |o: usize| u16::from_be_bytes([hb[o], hb[o + 1]]);
    let u32at = |o: usize| u32::from_be_bytes(hb[o..o + 4].try_into().unwrap());
    let header = FrameHeader {
        magic: u16at(0),
        version: hb[2],
        msg_type: hb[3],
        content_type: hb[4],
        compression_type: hb[5],
        flags: u16at(6),
        payload_len: u32at(8),
        meta_len: u32at(12),
        message_id: u64::from_be_bytes(hb[16..24].try_into().unwrap()),
        sequence: u32at(24),
        reserved: u32at(28),
    };
    let bad = |m: &str| std::io::Error::new(std::io::ErrorKind::InvalidData, m.to_string());
    if header.magic != MAGIC || header.version != VERSION {
        return Err(bad("bad magic/version"));
    }
    if header.meta_len > 1 << 20 || header.payload_len > 64 << 20 {
        return Err(bad("implausible lengths"));
    }
    let mut meta = vec![0u8; header.meta_len as usize];
    r.read_exact(&mut meta)?;
    let mut payload = vec![0u8; header.payload_len as usize];
    r.read_exact(&mut payload)?;
    let mut cb = [0u8; 4];
    r.read_exact(&mut cb)?;
    let crc = u32::from_be_bytes(cb);
    let mut all = hb.to_vec();
    all.extend_from_slice(&meta);
    all.extend_from_slice(&payload);
    if crc32(&all) != crc {
        return Err(bad("CRC mismatch"));
    }
    if header.flags & F_SIGNED != 0 {
        let mut sig = [0u8; 64]; // Ed25519 signature; not verified by this reference
        r.read_exact(&mut sig)?;
    }
    Ok(Frame { header, meta, payload, crc32: crc })
}

fn recv(port: u16) {
    let frames = Arc::new([AtomicUsize::new(0), AtomicUsize::new(0), AtomicUsize::new(0)]);
    let bytes = Arc::new(AtomicUsize::new(0));
    let errors = Arc::new(AtomicUsize::new(0));
    let stop = Arc::new(AtomicBool::new(false));
    for p in 0..3usize {
        let listener = TcpListener::bind(("0.0.0.0", port + p as u16)).expect("bind");
        let (frames, bytes, errors, stop) = (frames.clone(), bytes.clone(), errors.clone(), stop.clone());
        thread::spawn(move || {
            for conn in listener.incoming().flatten() {
                let (frames, bytes, errors, stop) = (frames.clone(), bytes.clone(), errors.clone(), stop.clone());
                thread::spawn(move || {
                    // one thread per connection
                    let mut writer = conn.try_clone().expect("clone");
                    let mut reader = BufReader::with_capacity(1 << 16, conn);
                    let mut next = 1u64;
                    loop {
                        let f = match read_frame(&mut reader) {
                            Ok(f) => f,
                            Err(e) => {
                                if e.kind() != std::io::ErrorKind::UnexpectedEof {
                                    errors.fetch_add(1, Ordering::SeqCst);
                                }
                                return;
                            }
                        };
                        frames[p].fetch_add(1, Ordering::SeqCst);
                        bytes.fetch_add(f.payload.len(), Ordering::SeqCst);
                        if f.header.flags & F_ACK_REQUESTED != 0 {
                            let meta = format!(
                                "{{\"ack\":[{}],\"control\":\"ACK\",\"priority\":{},\"queue_depth\":0,\"source_node_id\":\"rust-node-2\",\"window\":32}}",
                                f.header.message_id, p
                            );
                            let mut ack = Frame {
                                header: FrameHeader { msg_type: CONTROL, flags: PRIORITY_FLAGS[p], message_id: next, ..Default::default() },
                                meta: meta.into_bytes(),
                                payload: vec![],
                                crc32: 0,
                            };
                            next += 1;
                            let _ = writer.write_all(&encode(&mut ack));
                        }
                        if String::from_utf8_lossy(&f.meta).contains("\"control\":\"SHUTDOWN\"") {
                            stop.store(true, Ordering::SeqCst);
                        }
                    }
                });
            }
        });
    }
    println!("READY {port}");
    while !stop.load(Ordering::SeqCst) {
        thread::sleep(Duration::from_millis(20));
    }
    thread::sleep(Duration::from_millis(100));
    println!(
        "{{\"frames\":{{\"control\":{},\"normal\":{},\"bulk\":{}}},\"payload_bytes\":{},\"errors\":{}}}",
        frames[0].load(Ordering::SeqCst),
        frames[1].load(Ordering::SeqCst),
        frames[2].load(Ordering::SeqCst),
        bytes.load(Ordering::SeqCst),
        errors.load(Ordering::SeqCst)
    );
}

fn send(host: &str, port: u16, file: &str, batch: usize) {
    let mut conns: Vec<TcpStream> = (0..3).map(|p| TcpStream::connect((host, port + p as u16)).expect("connect")).collect();
    let mut pending = [0usize; 3];
    let mut id = 0u64;
    let mut write = |conns: &mut Vec<TcpStream>, p: usize, msg_type: u8, meta: String, payload: Vec<u8>| {
        id += 1;
        let mut f = Frame {
            header: FrameHeader { msg_type, flags: PRIORITY_FLAGS[p] | F_ACK_REQUESTED, message_id: id, ..Default::default() },
            meta: meta.into_bytes(),
            payload,
            crc32: 0,
        };
        conns[p].write_all(&encode(&mut f)).expect("write");
        pending[p] += 1;
    };
    for p in 0..3 {
        write(&mut conns, p, CONTROL, format!("{{\"control\":\"HELLO\",\"node_id\":\"rust-node-1\",\"priority\":{p},\"role\":\"{}\",\"source_node_id\":\"rust-node-1\"}}", ROLES[p]), vec![]);
    }
    let data = fs::read_to_string(file).expect("read file");
    let lines: Vec<&str> = data.lines().filter(|l| !l.trim().is_empty()).collect();
    for (i, chunk) in lines.chunks(batch.max(1)).enumerate() {
        let block = chunk.join("\n") + "\n";
        let meta = format!(
            "{{\"fact_count\":{},\"priority\":1,\"query_id\":\"rust-batch-{i}\",\"raw_bytes\":{},\"reliability\":\"must\",\"source_node_id\":\"rust-node-1\"}}",
            chunk.len(),
            block.len()
        );
        write(&mut conns, 1, FACT_BATCH, meta, block.into_bytes());
    }
    write(&mut conns, 0, CONTROL, "{\"control\":\"PING\",\"priority\":0,\"source_node_id\":\"rust-node-1\"}".into(), vec![]);
    let mut acked = 0;
    for (p, c) in conns.iter().enumerate() {
        let mut r = BufReader::new(c.try_clone().expect("clone"));
        while pending[p] > 0 {
            let f = read_frame(&mut r).expect("ack");
            let meta = String::from_utf8_lossy(&f.meta).to_string();
            if meta.contains("\"control\":\"ACK\"") {
                let n = meta.split("\"ack\":[").nth(1).and_then(|s| s.split(']').next()).map(|s| s.split(',').filter(|x| !x.is_empty()).count()).unwrap_or(0);
                pending[p] = pending[p].saturating_sub(n);
                acked += n;
            }
        }
    }
    println!("{{\"facts\":{},\"frames_acked\":{acked}}}", lines.len());
}

fn main() {
    let a: Vec<String> = env::args().collect();
    match a.get(1).map(String::as_str) {
        Some("recv") => recv(a.get(2).and_then(|p| p.parse().ok()).unwrap_or(9100)),
        Some("send") => send(
            a.get(2).map(String::as_str).unwrap_or("127.0.0.1"),
            a.get(3).and_then(|p| p.parse().ok()).unwrap_or(9100),
            a.get(4).map(String::as_str).unwrap_or("../../data/ufcs_sample.jsonl"),
            a.get(5).and_then(|b| b.parse().ok()).unwrap_or(1000),
        ),
        _ => {
            eprintln!("usage: ufcsframe recv PORT | send HOST PORT FILE BATCH");
            std::process::exit(1);
        }
    }
}
