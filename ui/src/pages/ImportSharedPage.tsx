import { useNavigate, useParams } from 'react-router-dom'
import { ImportModal } from './RulesPage'

/** Landing page for shared rule-pack links (/r/:code). */
export default function ImportSharedPage() {
  const { code } = useParams()
  const navigate = useNavigate()

  return (
    <ImportModal
      initialCode={code}
      onClose={() => navigate('/rules')}
      onImported={() => navigate('/rules?imported=1')}
    />
  )
}
