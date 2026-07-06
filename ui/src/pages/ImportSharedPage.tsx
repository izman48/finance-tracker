import { useNavigate, useParams } from 'react-router-dom'
import ImportRulePackModal from '../components/ImportRulePackModal'

/** Landing page for shared rule-pack links (/r/:code). */
export default function ImportSharedPage() {
  const { code } = useParams()
  const navigate = useNavigate()

  return (
    <ImportRulePackModal
      initialCode={code}
      onClose={() => navigate('/rules')}
      onImported={() => navigate('/rules?imported=1')}
    />
  )
}
