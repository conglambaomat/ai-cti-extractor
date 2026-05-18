# Autonomous Mode Quickstart

> Mục tiêu: Claude Code CLI tự code dự án 24/7. Bạn treo máy, sáng dậy chạy `bash scripts/morning-check.sh` để xem tiến độ.

## Trước khi khởi động

### 1. API keys (bắt buộc — Claude không tạo được)

Copy template và điền:

```bash
cp .env.example .env
```

Mở `.env`, set ít nhất 2 key:

```bash
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini
OPENAI_API_KEY=sk-...

# (Optional, recommend) MCP context7 cho docs lookup
# Edit .claude/.mcp.json, replace YOUR_CONTEXT7_API_KEY
```

OpenCTI/MISP/TAXII tokens có thể để trống — Phase 1-2 dùng dev instance local.

### 2. Cost cap (default $90)

Mặc định circuit breaker dừng ở $90 (10% headroom dưới $100 budget). Để đổi:

```bash
# Powershell
$env:CK_LLM_COST_CAP_USD="200"

# Bash
export CK_LLM_COST_CAP_USD=200
```

Hoặc set trong `.env`:
```
CK_LLM_COST_CAP_USD=200
```

### 3. Verify hooks active

```bash
echo '{"hook_event_name":"SessionStart","matcher":"startup","session_id":"test","cwd":"'$(pwd)'"}' \
  | node .claude/hooks/session-init.cjs
```
Output cần thấy: `Project: single-repo | Plan naming: ...`

### 4. Power + display settings (Windows)

Để máy không sleep khi treo 24/7:

```powershell
# Run as Admin
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
powercfg /change monitor-timeout-ac 30  # màn hình tắt sau 30 phút, OK
```

## Khởi động autonomous run

Mở Claude Code CLI tại `E:\OPENCTI\claudekit-engineer-main\`:

```bash
claude
```

Trong session, gõ:

```
/ck:plan Phase 1: ingestion (PDF/HTML/MD/TXT/URL) + regex IOC extraction + minimal STIX bundle (report, indicator, relationship) + OpenCTI export round-trip. Autonomous mode — proceed without my approval, follow CLAUDE.md "Autonomous Mode Operating Procedure" section.
```

Planner sẽ:
- Đọc CLAUDE.md autonomous procedure
- Spawn 2-3 researcher subagent
- Output plan tại `plans/<date>-<slug>/`
- KHÔNG hỏi 3-8 câu validation (autonomous mode bypass)
- Tự động trigger `/ck:cook` ngay sau khi plan xong

Sau đó để máy chạy. Bạn có thể đóng terminal — `claude` chạy trong background.

## Theo dõi tiến độ

### Sáng dậy

```bash
bash scripts/morning-check.sh
```

Output cho thấy:
1. **Halt markers** — Claude đã dừng vì cost cap hay lỗi không tự fix được
2. **Git activity 24h** — đã commit gì
3. **LLM cost** — đã tiêu bao nhiêu
4. **Pause/halt reports** — chỗ Claude bị stuck cần bạn intervene
5. **Test status** — có failing test không
6. **Working tree** — có uncommitted gì
7. **Active plan** — phase nào đang làm
8. **Recent journal entries** — decisions Claude đã đưa ra

### Real-time monitoring (optional)

```bash
# Tail commit log
watch -n 60 'git log --oneline -10'

# Tail cost ledger
tail -f .claude/.cost-ledger.jsonl

# Tail hook logs
tail -f .claude/hooks/.logs/hook-log.jsonl
```

## Khi cần intervene

### Có pause report → Claude bị stuck

```bash
ls plans/reports/PAUSED-*
cat plans/reports/PAUSED-<latest>.md
```

Đọc nội dung, fix vấn đề (e.g., add API key, install missing tool, clarify requirement), rồi:

```bash
# Mở Claude session, gõ:
"Resume from plans/reports/PAUSED-<file>.md. Issue resolved: <what you did>."
```

### Cost cap hit → Claude dừng vì $$

```bash
cat .claude/.HALT-COST          # xem total spent
ls plans/reports/COST-CAP-HIT-*  # report chi tiết
```

3 lựa chọn:
- **Tăng budget:** `export CK_LLM_COST_CAP_USD=200`, `rm .claude/.HALT-COST`, restart Claude
- **Switch local LLM:** edit `.env` set `LLM_PROVIDER=local`, `LOCAL_LLM_BASE_URL=http://localhost:11434/v1`, install Ollama, `rm .claude/.HALT-COST`
- **Stop:** đợi đến tháng sau / wallet refill

### Test fail loop

Nếu morning-check thấy nhiều `PAUSED-*` cùng 1 task → Claude retry 3x đều fail. Đọc report, có thể là:
- Bug logic Claude không tự nhìn ra → bạn debug + commit fix
- Missing dependency → `pip install <x>`
- Misunderstanding spec → update CLAUDE.md hoặc docs/ rồi resume

### Force pause autonomous run

```bash
# Tạo halt marker thủ công
touch .claude/.HALT-MANUAL
```

(Note: `.HALT-MANUAL` chưa có hook reading; dùng Ctrl+C trong Claude session là cách chính. Hoặc kill process.)

## Realistic expectations

### Tuần đầu (Phase 1)
- Day 1: planner + researchers chạy ~30 min, sinh plan ~7 phase
- Day 1-3: bootstrap pyproject, docker-compose, db schema
- Day 3-7: ingestion parsers + IOC extractor + tests
- Day 5-10: STIX builders + validators + OpenCTI roundtrip
- Cost: ~$5-15 (mostly research phase)

### Tuần 2-4 (Phase 1 hoàn thiện)
- Edge cases, refactor, code review iterations
- Cost: ~$3-8

### Tháng 2-3 (Phase 2 — encoders + ATT&CK)
- **Đây là lúc bạn cần intervene nhiều nhất**
- Dataset acquisition (AnnoCTR, AZERG) cần action thủ công
- Confidence threshold calibration cần data thật

### Tháng 4-6 (Phase 3 — RAG + LLM judge)
- Cost cao nhất — LLM judge call mỗi extraction
- Cost: $20-50/tháng nếu cache tốt, $200+/tháng nếu cache miss

### Tháng 7-12 (Phase 4 — benchmark + Sigma)
- Custom benchmark annotation **bạn phải làm thủ công** (Claude không đủ rigor cho thesis defense)
- Cost: thấp ($5-10/tháng)

## Failure modes phổ biến và cách phát hiện sớm

| Triệu chứng | Có thể là | Cách check |
|---|---|---|
| Cost tăng nhanh bất thường | LLM cache miss | `tail .claude/.cost-ledger.jsonl` xem có call lặp |
| Nhiều commit nhỏ, không phase tiến | Retry loop | `git log --since=1.day -p \| head -200` |
| Test pass nhưng không có code mới | Mock-only tests | grep test files for `Mock\|patch\|MagicMock` |
| STIX bundle nhưng OpenCTI reject | Validation gap | Manual check 1 bundle qua `stix2 validate` |
| Plan agent skip phases | Plan parse bug | Cat `plans/<id>/plan.md` xem table |
| Long phases (>3 ngày 1 phase) | Stuck nhưng chưa pause | Check journal, chia phase nhỏ hơn |

## Câu hỏi chưa giải quyết

1. Bạn có Ollama local cài chưa? (Phòng khi cost cap hit, fallback local LLM cần Ollama running)
2. GitHub remote — chưa setup. Push sẽ fail. Tạo repo trên github.com rồi `git remote add origin <url>`
3. OpenCTI dev instance — Phase 1 cần. Bạn có muốn tôi tạo `docker-compose.opencti.yml` ngay hay để planner tự design ở Phase 1?
