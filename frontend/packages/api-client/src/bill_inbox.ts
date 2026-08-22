import { extractApiError } from './errors'
import { API_BASE } from './http'

export type BillInboxUpload = {
  status: 'ready'
  ingest_id: string
  ledger_id: string
  account_id: string
  original_filename: string
  content_type: string
  size: number
  sha256: string
  uploaded_at: string
}

export async function uploadBill(
  token: string,
  payload: { ledgerId: string; accountId: string; file: File },
): Promise<BillInboxUpload> {
  const body = new FormData()
  body.append('ledger_id', payload.ledgerId)
  body.append('account_id', payload.accountId)
  body.append('file', payload.file)
  const response = await fetch(`${API_BASE}/bill-inbox/upload`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body,
  })
  if (!response.ok) throw await extractApiError(response)
  return response.json()
}
