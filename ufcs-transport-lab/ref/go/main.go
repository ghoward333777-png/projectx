// Reference Go implementation of the UFCS-FQL/1 sender/receiver pair.
// Standard library only; wire-compatible with the PHP lab nodes.
//
//	go run . recv -port 9100                      # Node 2: listens on 9100/9101/9102
//	go run . send -port 9100 -file ../../data/ufcs_sample.jsonl -batch 100
//
// Supported payload codecs: NONE and GZIP (Zstd is not in the Go standard
// library; plug in github.com/klauspost/compress/zstd for code 1).
package main

import (
	"bufio"
	"bytes"
	"compress/gzip"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"hash/crc32"
	"io"
	"net"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"
)

const (
	Magic      = 0xF051
	Version    = 1
	HeaderLen  = 32
	FactBatch  = 0
	Control    = 2
	Text       = 0
	CNone      = 0
	CGzip      = 2
	FControl   = 0x0001
	FNormal    = 0x0002
	FBulk      = 0x0004
	FSigned    = 0x0008
	FAckReq    = 0x0020
	MaxMeta    = 1 << 20
	MaxPayload = 64 << 20
)

type FrameHeader struct {
	Magic           uint16
	Version         uint8
	MsgType         uint8
	ContentType     uint8
	CompressionType uint8
	Flags           uint16
	PayloadLen      uint32
	MetaLen         uint32
	MessageID       uint64
	Sequence        uint32
	Reserved        uint32
}

type Frame struct {
	Header    FrameHeader
	Meta      []byte
	Payload   []byte
	CRC32     uint32
	Signature []byte
}

// Encode serialises a frame (big-endian header, meta, payload, CRC32).
func Encode(f *Frame) []byte {
	f.Header.Magic, f.Header.Version = Magic, Version
	f.Header.MetaLen, f.Header.PayloadLen = uint32(len(f.Meta)), uint32(len(f.Payload))
	f.Header.Flags &^= FSigned
	buf := &bytes.Buffer{}
	binary.Write(buf, binary.BigEndian, f.Header) // struct has no padding: exactly 32 bytes
	buf.Write(f.Meta)
	buf.Write(f.Payload)
	f.CRC32 = crc32.ChecksumIEEE(buf.Bytes())
	binary.Write(buf, binary.BigEndian, f.CRC32)
	return buf.Bytes()
}

// ReadFrame reads one frame from a stream and verifies its CRC32.
func ReadFrame(r io.Reader) (*Frame, error) {
	hb := make([]byte, HeaderLen)
	if _, err := io.ReadFull(r, hb); err != nil {
		return nil, err
	}
	var h FrameHeader
	binary.Read(bytes.NewReader(hb), binary.BigEndian, &h)
	if h.Magic != Magic || h.Version != Version {
		return nil, fmt.Errorf("bad magic/version %04x/%d", h.Magic, h.Version)
	}
	if h.MetaLen > MaxMeta || h.PayloadLen > MaxPayload {
		return nil, errors.New("implausible lengths")
	}
	body := make([]byte, int(h.MetaLen)+int(h.PayloadLen))
	if _, err := io.ReadFull(r, body); err != nil {
		return nil, err
	}
	cb := make([]byte, 4)
	if _, err := io.ReadFull(r, cb); err != nil {
		return nil, err
	}
	crc := binary.BigEndian.Uint32(cb)
	if crc32.Update(crc32.ChecksumIEEE(hb), crc32.IEEETable, body) != crc {
		return nil, errors.New("crc mismatch")
	}
	f := &Frame{Header: h, Meta: body[:h.MetaLen], Payload: body[h.MetaLen:], CRC32: crc}
	if h.Flags&FSigned != 0 { // Ed25519 signature follows; this reference does not verify it
		f.Signature = make([]byte, 64)
		if _, err := io.ReadFull(r, f.Signature); err != nil {
			return nil, err
		}
	}
	return f, nil
}

func priorityFlag(p int) uint16 { return []uint16{FControl, FNormal, FBulk}[p] }

func decompress(code uint8, data []byte) ([]byte, error) {
	switch code {
	case CNone:
		return data, nil
	case CGzip:
		zr, err := gzip.NewReader(bytes.NewReader(data))
		if err != nil {
			return nil, err
		}
		return io.ReadAll(zr)
	}
	return nil, fmt.Errorf("codec %d not supported by the Go reference", code)
}

// --- UFCS fingerprint (SHA-256(norm(s)|norm(p)|norm(o)|polarity)) -----------

func pyFloat(f float64) string {
	s := strconv.FormatFloat(f, 'e', -1, 64) // d.ddde±XX, shortest round-trip digits
	mant, expS, _ := strings.Cut(s, "e")
	neg := strings.HasPrefix(mant, "-")
	mant = strings.TrimPrefix(mant, "-")
	digits := strings.TrimRight(strings.Replace(mant, ".", "", 1), "0")
	exp, _ := strconv.Atoi(expS)
	sign := ""
	if neg {
		sign = "-"
	}
	if digits == "" {
		return sign + "0.0"
	}
	decpt := exp + 1
	if decpt > -4 && decpt <= 16 {
		switch {
		case decpt <= 0:
			return sign + "0." + strings.Repeat("0", -decpt) + digits
		case decpt >= len(digits):
			return sign + digits + strings.Repeat("0", decpt-len(digits)) + ".0"
		default:
			return sign + digits[:decpt] + "." + digits[decpt:]
		}
	}
	m := digits[:1]
	if len(digits) > 1 {
		m += "." + digits[1:]
	}
	es := "+"
	if exp < 0 {
		es, exp = "-", -exp
	}
	return fmt.Sprintf("%s%se%s%02d", sign, m, es, exp)
}

func pyStr(v any) string {
	switch x := v.(type) {
	case string:
		return x
	case bool:
		if x {
			return "True"
		}
		return "False"
	case nil:
		return "None"
	case json.Number:
		if i, err := strconv.ParseInt(string(x), 10, 64); err == nil && !strings.ContainsAny(string(x), ".eE") {
			return strconv.FormatInt(i, 10)
		}
		f, _ := x.Float64()
		return pyFloat(f)
	}
	b, _ := json.Marshal(v)
	return string(b)
}

func norm(v any) string { return strings.Join(strings.Fields(strings.ToLower(pyStr(v))), " ") }

func validate(rec map[string]any) error {
	n, ok := rec["nucleus"].(map[string]any)
	if !ok {
		return errors.New("missing nucleus")
	}
	pol, _ := rec["polarity"].(string)
	fp, _ := rec["semantic_fingerprint"].(string)
	sum := sha256.Sum256([]byte(norm(n["subject"]) + "|" + norm(n["predicate"]) + "|" + norm(n["object"]) + "|" + pol))
	if hex.EncodeToString(sum[:]) != strings.ToLower(fp) {
		return errors.New("semantic_fingerprint does not re-validate")
	}
	return nil
}

// --- Node 2 -----------------------------------------------------------------

type rxStats struct {
	sync.Mutex
	Frames    map[string]int `json:"frames"`
	Facts     int            `json:"facts"`
	Admitted  int            `json:"admitted"`
	Rejected  int            `json:"rejected"`
	Errors    int            `json:"errors"`
	Signed    int            `json:"signed_frames"`
	PayloadIn int            `json:"payload_bytes"`
}

func recv(port int) {
	stats := &rxStats{Frames: map[string]int{}}
	seen := map[string]bool{}
	done := make(chan struct{})
	var once sync.Once
	roles := []string{"control", "normal", "bulk"}
	for p := 0; p < 3; p++ {
		ln, err := net.Listen("tcp", fmt.Sprintf("0.0.0.0:%d", port+p))
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(2)
		}
		go func(ln net.Listener, p int) {
			for {
				conn, err := ln.Accept()
				if err != nil {
					return
				}
				go func(conn net.Conn) { // one goroutine per connection
					defer conn.Close()
					r := bufio.NewReaderSize(conn, 1<<16)
					var next uint64 = 1
					for {
						f, err := ReadFrame(r)
						if err != nil {
							if err != io.EOF {
								stats.Lock()
								stats.Errors++
								stats.Unlock()
							}
							return
						}
						meta := map[string]any{}
						json.Unmarshal(f.Meta, &meta)
						stats.Lock()
						stats.Frames[roles[p]]++
						stats.PayloadIn += len(f.Payload)
						if f.Signature != nil {
							stats.Signed++
						}
						if f.Header.MsgType == FactBatch && f.Header.ContentType == Text {
							if data, err := decompress(f.Header.CompressionType, f.Payload); err != nil {
								stats.Errors++
							} else {
								for _, line := range bytes.Split(data, []byte("\n")) {
									if len(bytes.TrimSpace(line)) == 0 {
										continue
									}
									dec := json.NewDecoder(bytes.NewReader(line))
									dec.UseNumber()
									rec := map[string]any{}
									if dec.Decode(&rec) != nil {
										stats.Rejected++
										continue
									}
									stats.Facts++
									if validate(rec) != nil {
										stats.Rejected++
									} else if fp := rec["semantic_fingerprint"].(string); !seen[fp] {
										seen[fp] = true
										stats.Admitted++
									}
								}
							}
						}
						stats.Unlock()
						if f.Header.Flags&FAckReq != 0 {
							ack, _ := json.Marshal(map[string]any{"ack": []uint64{f.Header.MessageID}, "control": "ACK", "priority": p, "queue_depth": 0, "source_node_id": "go-node-2", "window": 32})
							conn.Write(Encode(&Frame{Header: FrameHeader{MsgType: Control, Flags: priorityFlag(p), MessageID: next}, Meta: ack}))
							next++
						}
						if meta["control"] == "SHUTDOWN" {
							once.Do(func() { close(done) })
						}
					}
				}(conn)
			}
		}(ln, p)
	}
	fmt.Printf("READY %d\n", port)
	<-done
	time.Sleep(100 * time.Millisecond)
	stats.Lock()
	out, _ := json.Marshal(stats)
	stats.Unlock()
	fmt.Println(string(out))
}

// --- Node 1 -----------------------------------------------------------------

func send(host string, port int, file string, batch int) {
	conns := make([]net.Conn, 3)
	for p := range conns {
		c, err := net.Dial("tcp", fmt.Sprintf("%s:%d", host, port+p))
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(2)
		}
		conns[p] = c
	}
	var id uint64
	pending := make([]int, 3)
	write := func(p int, msgType, content, codec uint8, meta map[string]any, payload []byte) {
		id++
		meta["priority"] = p
		meta["source_node_id"] = "go-node-1"
		mb, _ := json.Marshal(meta)
		f := &Frame{Header: FrameHeader{MsgType: msgType, ContentType: content, CompressionType: codec, Flags: priorityFlag(p) | FAckReq, MessageID: id}, Meta: mb, Payload: payload}
		conns[p].Write(Encode(f))
		pending[p]++
	}
	for p := range conns {
		write(p, Control, Text, CNone, map[string]any{"control": "HELLO", "node_id": "go-node-1", "role": []string{"control", "normal", "bulk"}[p]}, nil)
	}
	data, err := os.ReadFile(file)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	lines := bytes.Split(bytes.TrimSpace(data), []byte("\n"))
	raw, sent := 0, 0
	for i := 0; i < len(lines); i += batch {
		end := min(i+batch, len(lines))
		block := append(bytes.Join(lines[i:end], []byte("\n")), '\n')
		var zb bytes.Buffer
		zw, _ := gzip.NewWriterLevel(&zb, 6)
		zw.Write(block)
		zw.Close()
		write(1, FactBatch, Text, CGzip, map[string]any{"fact_count": end - i, "query_id": fmt.Sprintf("go-batch-%d", i/batch), "raw_bytes": len(block), "reliability": "must"}, zb.Bytes())
		raw += len(block)
		sent += zb.Len()
	}
	write(0, Control, Text, CNone, map[string]any{"control": "PING"}, nil)
	acked := 0
	for p, c := range conns { // collect every ACK
		r := bufio.NewReader(c)
		for pending[p] > 0 {
			f, err := ReadFrame(r)
			if err != nil {
				fmt.Fprintln(os.Stderr, "ack read:", err)
				os.Exit(3)
			}
			var m struct {
				Control string   `json:"control"`
				Ack     []uint64 `json:"ack"`
			}
			json.Unmarshal(f.Meta, &m)
			if m.Control == "ACK" {
				pending[p] -= len(m.Ack)
				acked += len(m.Ack)
			}
		}
		c.Close()
	}
	out, _ := json.Marshal(map[string]any{"facts": len(lines), "raw_bytes": raw, "payload_bytes": sent, "frames_acked": acked})
	fmt.Println(string(out))
}

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "usage: ufcsframe recv|send [flags]")
		os.Exit(1)
	}
	fs := flag.NewFlagSet(os.Args[1], flag.ExitOnError)
	host := fs.String("host", "127.0.0.1", "Node 2 host")
	port := fs.Int("port", 9100, "base port (control); +1 normal, +2 bulk")
	file := fs.String("file", "../../data/ufcs_sample.jsonl", "UFCS JSONL to send")
	batch := fs.Int("batch", 1000, "facts per FACT_BATCH")
	fs.Parse(os.Args[2:])
	switch os.Args[1] {
	case "recv":
		recv(*port)
	case "send":
		send(*host, *port, *file, *batch)
	default:
		fmt.Fprintln(os.Stderr, "unknown command", os.Args[1])
		os.Exit(1)
	}
}
