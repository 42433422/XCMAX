/** Wire response from both legacy and ERP-Mod customer read endpoints. */
export interface Customer {
  id: number
  /** Canonical API readback name; legacy callers may still use name/unit_name. */
  customer_name?: string
  name?: string
  unit_name?: string
  contact_person?: string
  contact_phone?: string
  contact_address?: string
  address?: string
  version?: number
  created_at?: string
  updated_at?: string
}

/** The backend validates aliases and rejects conflicting customer names. */
export interface CustomerCreateDTO {
  name?: string
  customer_name?: string
  unit_name?: string
  contact_person?: string
  contact_phone?: string
  contact_address?: string
  address?: string
}

export interface CustomerUpdateDTO extends Partial<CustomerCreateDTO> {
  /** Optimistic concurrency precondition, validated server-side. */
  expected_version?: number
}

/** Result unknown means no blind retry, regardless of HTTP status. */
export interface CustomerMutationReceipt<T = Customer> {
  success: boolean
  data?: T
  message?: string
  error_code?: string
  outcome?: 'unknown' | 'committed' | 'rejected'
  retryable?: boolean
  reconciliation_required?: boolean
}
