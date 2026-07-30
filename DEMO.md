# Demo scripts

A tight, 3-minute demo. Practice this verbatim.

## ✏️ Sketch → Azure (headline demo)

**Setup:** `cd whiteboard-to-app && ./run-live.sh` — badge shows 🟢 live.
Have your architecture diagram image ready.

1. **(0:00)** "Every architecture starts as a diagram. What if the diagram *was*
   the deploy button?"
2. **(0:20)** Upload the diagram photo. GPT-4o parses it live into a colored
   node graph (App Gateway, WAF, APIM, AKS, Key Vault, ACR, …).
3. **(1:00)** Click **Generate IaC**. Real Bicep scrolls — point out it's a full
   private-AKS topology, not a snippet.
4. **(1:40)** Click **Validate & deploy**. `az bicep build` validates all ~14 ARM
   resources, and the **demo-safe subset really provisions** — show the live
   Key Vault URL, Managed Identity, and ACR that appear.
5. **(2:30)** Open the Azure portal / `az resource list -g rg-whiteboard-demo` to
   prove the resources are real. Land: "from a picture to real Azure resources,
   in under three minutes."

> Honesty line for judges: heavy resources (App Gateway/APIM/AKS) are
> validated-only because they take many minutes and cost money; the cheap subset
> is deployed for real so the loop is genuinely end-to-end.

**Reset:** `./cleanup-demo.sh` between runs.
