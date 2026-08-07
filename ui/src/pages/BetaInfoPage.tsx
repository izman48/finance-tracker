import { type ReactNode } from 'react'
import { Link } from 'react-router-dom'

const contactEmail = import.meta.env.VITE_BETA_CONTACT_EMAIL

/** Falls back to prose when the deployment hasn't set a contact address —
 *  a `mailto:` built from the fallback wording would be a dead link. */
function Contact() {
  if (!contactEmail) return <>the person who invited you</>
  return <a className="btn-link" href={`mailto:${contactEmail}`}>{contactEmail}</a>
}

function LegalShell({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="max-w-3xl mx-auto px-4 py-10 sm:py-16">
      <div className="card-pad prose-copy">
        <p className="chip-info inline-flex mb-4">Invite-only beta</p>
        <h1 className="font-display font-bold text-3xl text-slate-50 mb-6">{title}</h1>
        <div className="space-y-5 text-sm leading-relaxed text-slate-300">{children}</div>
      </div>
    </div>
  )
}

export function PrivacyPage() {
  return (
    <LegalShell title="Privacy for the beta">
      <p>
        nilu. is a private, invite-only budgeting beta. The beta operator is responsible for this
        instance. Questions or requests about your data: <Contact />.
      </p>
      <section>
        <h2 className="font-display font-semibold text-slate-100 text-lg mb-1">What we process</h2>
        <p>We process your email address and password hash to operate your account. When you choose to connect a bank, we receive account, balance and transaction data through TrueLayer so we can provide the dashboard, forecast and spending insights you request.</p>
      </section>
      <section>
        <h2 className="font-display font-semibold text-slate-100 text-lg mb-1">How it is stored — we can’t read it</h2>
        <p>Your financial data — transaction amounts, descriptions and merchants, account names and balances, and your bank connection tokens — is encrypted in our database with a key that is yours. That key is unlocked only by your password or your one-time recovery code, and we store neither. So we cannot decrypt your financial data at rest: our database, and any backup of it, is unreadable without you. Your password itself is never stored, only a salted bcrypt hash of it.</p>
        <p className="mt-3">Two honest limits, so this isn’t overstated. While you are signed in, the app necessarily holds your key in memory to show you your own dashboard — that is the one window in which your data is readable. And a few non-financial fields stay unencrypted so the app can work at all: your email address, and transaction dates, categories and account types.</p>
      </section>
      <section>
        <h2 className="font-display font-semibold text-slate-100 text-lg mb-1">Why and who receives it</h2>
        <p>We use this information only to run nilu., secure it, and send account emails such as password resets. TrueLayer and the email provider are used as service providers where necessary. We do not sell data or use advertising/tracking scripts in the dashboard.</p>
      </section>
      <section>
        <h2 className="font-display font-semibold text-slate-100 text-lg mb-1">Your control</h2>
        <p>You can disconnect a bank or delete your account in the app. Deleting an account removes its application data; contact the beta operator for help or a privacy request. Keep your recovery code safe: without it and your password, encrypted bank data cannot be recovered.</p>
      </section>
      <p>This notice is a plain-language beta summary, not a substitute for the deployment operator completing its legal review before a public launch.</p>
    </LegalShell>
  )
}

export function TermsPage() {
  return (
    <LegalShell title="Beta terms and important limits">
      <p>nilu. is an invite-only experimental personal-finance dashboard. It is provided for your own use while the beta is running and may change, be unavailable, or be withdrawn.</p>
      <section>
        <h2 className="font-display font-semibold text-slate-100 text-lg mb-1">Not financial advice</h2>
        <p>Figures, forecasts and nudges are estimates based only on the accounts, balances, transactions and assumptions you provide. They are not financial, investment, tax, credit or debt advice, and they are not a guarantee that a payment will clear or that spending is affordable.</p>
      </section>
      <section>
        <h2 className="font-display font-semibold text-slate-100 text-lg mb-1">Open banking</h2>
        <p>Bank connections are read-only. nilu. cannot move money and never asks for your bank password. You explicitly choose whether to connect via TrueLayer; review the connection details shown by your bank and TrueLayer before approving.</p>
      </section>
      <section>
        <h2 className="font-display font-semibold text-slate-100 text-lg mb-1">Your responsibilities</h2>
        <p>Keep your password and recovery code private, connect only accounts you are allowed to access, and check important balances and payments with your bank. Tell the beta operator (<Contact />) if you find a problem.</p>
      </section>
      <p>nilu. itself is not presented as FCA-authorised. TrueLayer is the regulated open-banking provider used for connections.</p>
    </LegalShell>
  )
}

export function BetaNotice() {
  return (
    <p className="text-xs text-slate-500 leading-relaxed">
      Invite-only beta. By creating an account, you acknowledge the{' '}
      <Link to="/terms" className="btn-link">beta terms</Link> and{' '}
      <Link to="/privacy" className="btn-link">privacy summary</Link>.
    </p>
  )
}
