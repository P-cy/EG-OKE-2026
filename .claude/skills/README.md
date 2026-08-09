# Skills ของโปรเจกต์นี้

สกิลจาก [mattpocock/skills](https://github.com/mattpocock/skills) (MIT — ดู `LICENSE-mattpocock`)
คัดมาเฉพาะตัวที่ตรงกับงาน EG'OKE 2026 ไม่ได้เอามาทั้ง 35 ตัว

ก็อปมาเป็นไฟล์ธรรมดา ไม่ได้ผูกกับ marketplace → **แก้ได้ตามใจ** ให้เข้ากับโปรเจกต์
แลกกับการที่มันไม่อัปเดตตามต้นทาง (อยากได้ของใหม่ต้อง clone มาเทียบเอง)

ตัด `agents/openai.yaml` ของทุกสกิลออก — เป็นไฟล์สำหรับ Codex ไม่เกี่ยวกับ Claude Code

---

## เรียกเองได้ (พิมพ์ `/ชื่อ`)

| สกิล | ใช้ตอนไหน |
|---|---|
| `/grill-me` | ก่อนเริ่มงานใหญ่ — ให้ agent สัมภาษณ์จนตกลงกันได้จริงว่าจะทำอะไร |
| `/grill-with-docs` | เหมือน `/grill-me` แต่เก็บศัพท์ลง `CONTEXT.md` + ADR ไปด้วย |
| `/wait-what` | อ่านที่ agent พิมพ์แล้วไม่เข้าใจ — สั่งให้อธิบายใหม่แบบภาษาคน |
| `/handoff` | บทสนทนายาวจน context จะเต็ม — สรุปส่งต่อให้ session ใหม่ |
| `/improve-codebase-architecture` | สแกนหาจุดที่ควรรีแฟกเตอร์ แล้วออกรายงาน HTML |

## agent หยิบใช้เองได้ (หรือพิมพ์เรียกก็ได้)

| สกิล | ใช้ตอนไหน |
|---|---|
| `grilling` | ตัวสัมภาษณ์ที่อยู่เบื้องหลัง `/grill-me` |
| `diagnosing-bugs` | บั๊กยาก / ของช้าลง — บังคับให้สร้าง feedback loop ก่อนเดาสาเหตุ |
| `tdd` | เขียนเทสต์ก่อนโค้ด red-green-refactor |
| `codebase-design` | ศัพท์กลางเรื่อง deep module / seam / interface |
| `domain-modeling` | ตกลงศัพท์ในโปรเจกต์ ลง `CONTEXT.md` และ ADR |
| `research` | ให้ background agent ไปอ่าน doc/spec แล้วสรุปเป็นไฟล์พร้อมอ้างอิง |
| `wizard` | สร้างสคริปต์ bash พาคนทำ step ที่ agent ทำแทนไม่ได้ (ตั้ง credential, CI secret) |
| `prototype` | ลองของทิ้ง — เช็คว่า state model หรือหน้าตา UI เวิร์คไหม |
| `writing-for-agents` | ตอนแก้ `CLAUDE.md` / `AGENTS.md` / เขียนสกิลเอง |

---

## ที่ตั้งใจไม่เอามา

| สกิล | เหตุผล |
|---|---|
| `code-review` | ชนกับ `/code-review ultra` ที่มีอยู่แล้วใน Claude Code ซึ่งแรงกว่า (multi-agent บน cloud) และตัวนี้ต้องตั้ง issue tracker ก่อนถึงจะทำงาน |
| `to-spec` `to-tickets` `triage` `wayfinder` `implement` `setup-matt-pocock-skills` | เป็นชุด workflow ที่ต้องผูกกับ GitHub Issues หรือ Linear ก่อน — โปรเจกต์นี้ยังไม่ได้ใช้ issue tracker |
| `setup-pre-commit` | ติดตั้ง Husky + lint-staged + Prettier ซึ่งโปรเจกต์นี้ไม่ได้ใช้ Prettier และมี backend เป็น Python ด้วย (ใช้ ruff) — ไม่เข้ากันตรงๆ |
| `git-guardrails-claude-code` | บล็อกคำสั่ง git อันตราย ติดตั้งได้ถ้าอยากได้ แต่มันไปแก้ hooks ใน settings — ควรตัดสินใจเอง |
| `migrate-to-shoehorn` `scaffold-exercises` `setup-ts-deep-modules` `teach` `writing-*` | ไม่เกี่ยวกับโปรเจกต์นี้ |

---

## อยากได้ครบทั้งชุดแบบอัปเดตอัตโนมัติ

```
/plugin install mattpocock-skills
```

อยู่ใน marketplace ทางการของ Claude Code แล้ว — แต่ **อย่าทำพร้อมกับที่ก็อปไว้ตรงนี้**
ไม่งั้นสกิลจะมาซ้ำสองชุด ถ้าจะใช้ plugin ให้ลบโฟลเดอร์นี้ทิ้งก่อน

---

## หมายเหตุสำหรับโปรเจกต์นี้

หลายสกิลอ้างถึงไฟล์ `CONTEXT.md` ที่ราก repo (glossary ศัพท์ของโปรเจกต์) — **ตอนนี้ยังไม่มี**
จะได้มาตอนรัน `/grill-with-docs` ครั้งแรก ซึ่งน่าจะคุ้มสำหรับโปรเจกต์นี้เพราะศัพท์ปนไทย-อังกฤษเยอะ
(เควส/quest, บัตร/ticket, เหรียญ/coin, รอบโหวต/vote round, จุดสแกน/gate)
