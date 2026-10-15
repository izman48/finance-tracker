/** The privacy page's list of unencrypted fields (T-12-13). */
// Every unencrypted field group, in the API's exact words
// (api/app/core/privacy_plaintext.py; .github/scripts/check_privacy_copy.py
// fails CI if one goes missing here). T-12-13.
export const UNENCRYPTED_FIELDS: string[] = [
  "your email address",
  "dates and times, such as when a transaction, payment, statement or plan falls due and when a record was created or changed",
  "categories and the rules that set them, including budget categories and rule packs (their names, descriptions and patterns)",
  "the type and settings of each record and its on/off switches, such as how often a bill repeats, whether it is your payday, an account's role, or a record's status",
  "overdraft limits and card repayment settings, including a fixed repayment amount you choose",
  "the growth rate you set for a holding, and how many payments are left or planned",
  "your bank's own reference numbers for accounts and transactions, and their currency",
  "details of Claude connections you approve: the app's name, its web address and the access you granted",
  "your password and keys, only in protected form: a salted password hash, keys wrapped under your password or recovery code, and hashes of access tokens",
  "internal reference numbers that link one record to another",
]

export const DELETED_PLANNED_NOTE =
  "A planned item you delete stops counting at once, but it is kept, still encrypted, so changes Claude made to it keep their history. It is removed when you delete your account or your data is purged."
