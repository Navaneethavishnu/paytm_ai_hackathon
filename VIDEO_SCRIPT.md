# 3-minute demo video script: Merchant Success AI (Team Absolute AI)

The whole video is the app; there are no slides. Record one clip per part and join them in iMovie.
**Reset once, before Clip 1** (↺ Reset), then record Clips 1–6 in order *without* resetting: the four cases don't affect each other, and Clip 6 shows them all in History. If you must redo a case clip, click ↺ Reset, quickly re-run the earlier cases (chips are instant), then redo it. Keep the timeline on the **Graph** tab. Open **Ops approvals** once beforehand and type `Navaneethamahavishnu` as Reviewer (it is remembered).
**Best way to send text:** click the **chip** (button above the chat box). If you paste instead, paste the text *exactly* as below, so the cached answer is used and it replies instantly.

---

## Clip 1 · Intro (0:00–0:15)
**Screen:** the app home screen after Reset, timeline on **Graph** (all steps grey).

**Say:**
> Hi, I'm Navaneethamahavishnu from Team Absolute AI. This is Merchant Success AI, an AI teammate that doesn't just answer merchants, it closes their payment cases. On the left is what the merchant sees: a simple chat. On the right is the internal view for the operations team: every step the AI takes, drawn as a live graph.

---

## Clip 2 · Case 1: fixed automatically, in Tamil (0:15–0:50)
**Do:** Signed in as **Lakshmi Tiffin Centre** (PIN 0001 fills in) → chip **"Payout missing (Tamil)"**

**Or paste:**
```
என் ORD-1001 ₹2,400 பணம் இன்னும் என் வங்கிக்கு வரவில்லை
```

**Say:**
> A tiffin shop owner writes in Tamil: her two thousand four hundred rupees hasn't reached her bank.
> Watch the graph light up step by step. The purple steps are the AI: it understood the Tamil message and chose which systems to check. The payment succeeded, but the payout failed because of a bank timeout.
> Now the policy engine, plain rules and not the AI, decides: rule R-07, automatic. It retries the payout with an idempotency key so money can never go twice, then re-reads the bank status to confirm.
> She gets a reply in Tamil with the bank reference number, the UTR.

**Point at:** the green **Policy gate · R-07 · auto** step in the graph, then the reply with its **✓ Resolved** chip.

---

## Clip 3 · Case 2: human approval by Ops (0:50–1:35)
**Do:** Signed in as **Arun Mobiles** (PIN 0002) → chip **"Charged twice ₹12,000"** → wait until the **Ops approvals** tab badge pulses → click **Review in Ops approvals →** → **Approve** (the app jumps back to the graph)

**Or paste:**
```
Customer says they were charged twice for ORD-2001, ₹12,000. Please check.
```

**Say (before Approve):**
> A mobile shop's customer was charged twelve thousand rupees twice. The AI found the duplicate itself: same customer, same bill, ninety seconds apart.
> Twelve thousand is above the automatic refund limit, so rule R-22 pauses and asks a human. In the Ops approvals tab, the operations team sees the evidence: both payments, the duplicate highlighted, customer details masked.
> The approval is tied to a fingerprint, a hash, of exactly this evidence. If anything changes, nothing moves.

**Click Approve (the app jumps back to the graph), then say:**
> Approved. The refund runs, it's verified by reading the system again, and the merchant gets the refund ID.

---

## Clip 4 · Case 3: knowing when to stop (1:35–1:55)
**Do:** Signed in as **Sri Balaji Stores** (PIN 0003) → chip **"Someone else's order"** → point at the **red path to Escalate** in the graph

**Or paste:**
```
ORD-4001 for ₹48,000 never reached my account.
```

**Say:**
> Here a merchant asks about an order that actually belongs to another merchant. Rule G-01 stops everything: it raises a ticket for a specialist, and the reply never reveals that the order even exists. The AI can't be tricked into this either: it never chooses whose data it reads.

---

## Clip 5 · Case 4: customer consent plus Ops approval (1:55–2:40)
**Do:**
1. Left panel → **Customer** tab
2. Customer dropdown → **"Lalitha: ₹7,200 hall booking at Kumar Hotel"**
3. Click **⚡ Simulate double payment (ORD-6004)**
4. Customer taps **Refund one**
5. **Ops approvals** badge pulses → **Review in Ops approvals →** → **Approve**

**Nothing to type**: this case starts from a system event.

**Say (after step 3):**
> Now nobody has complained at all. A customer paid the same seven thousand two hundred rupee hall booking twice by mistake. The AI noticed on its own, and because paying twice is sometimes intentional, it asks the customer: keep both, or refund one? The hotel gets a heads-up too.

**After "Refund one":**
> The customer chose refund. But it's above five thousand rupees, so the operations team must also approve. Two keys: the customer agrees, and a human approves.

**After Approve:**
> Refunded, verified, and both the customer and the hotel are told. If the customer doesn't reply, no money moves.

---

## Clip 6 · Close (2:40–3:00)
**Screen:** click the **History** tab: every case you just ran, with its outcome, rule and who approved it. Then point at the counters in the top bar.

**Say:**
> Every case is stored and can be replayed step by step. So the AI proposes, the policy engine decides, and the verifier confirms. It's backed by 184 automated tests, and 300 chaos runs with systems failing a quarter of the time, with no crash and never a double payout or refund. Thank you, from Team Absolute AI.

---

### Everyday wording (tested live on 15 Nov and cached, so they reply instantly)

Use these instead of the chip texts if you want it to sound like a real shop owner. Paste them exactly.

| Case | Merchant | Tamil | English |
|---|---|---|---|
| 1 | M1001 | `சார், நேத்து ORD-1001 ல 2400 ரூபாய் payment வந்துச்சு, ஆனா இன்னும் என் bank account க்கு பணம் வரல. கொஞ்சம் பாருங்க.` | `Hi, I got ₹2,400 for order ORD-1001 yesterday but the money still hasn't come to my bank. Please check.` |
| 2 | M1002 | `சார், ஒரு customer ORD-2001 க்கு 12000 ரூபாய் ரெண்டு தடவை கட்டிட்டாருன்னு சொல்றாரு. கொஞ்சம் check பண்ணுங்க.` | `Hello, my customer is saying he paid two times for the same phone. Order ORD-2001, ₹12,000. Can you check and give back the extra money?` |
| 3 | M1003 | `சார், ORD-4001 க்கு 48000 ரூபாய் இன்னும் என் account க்கு வரல.` | `Sir, my payment for order ORD-4001, ₹48,000, still hasn't reached my account. Please help.` |

The agent replies in the language you write in.

### Quick reference

| Clip | Merchant / panel | PIN | Approval shown |
|---|---|---|---|
| 2 | Lakshmi Tiffin Centre | 0001 | none (R-07 auto) |
| 3 | M1002 Arun Mobiles | 0002 | **Ops approves** (R-22) |
| 4 | M1003 Sri Balaji Stores | 0003 | none (G-01 escalate) |
| 5 | Customer tab → Lalitha ₹7,200 | none | **Customer consent + Ops approves** (R-22) |

Close `.env` before recording, and never show keys or tokens on screen.
