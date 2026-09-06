import { Boxes } from 'lucide-react'
import { ErrorState,LoadingState } from '../components/common/PageState'
import { ModelCard } from '../components/models/ModelCard'
import { useDashboard } from '../context/DashboardContext'

export function ModelsPage(){const{data,loading,error,refresh}=useDashboard();if(loading)return <div className="page"><LoadingState/></div>;if(error||!data)return <div className="page"><ErrorState message={error??'Models could not be loaded.'} onRetry={()=>void refresh()}/></div>;return <div className="page"><header className="page-header"><div><p className="eyebrow">Model registry</p><h1>Monitored Models</h1><p>Health and evaluation coverage for every registered model.</p></div><div className="header-meta"><Boxes size={14}/> {data.models.length} active systems</div></header><div className="models-grid">{data.models.map((model,index)=><ModelCard key={model.id} model={model} primary={index===0}/>)}</div></div>}
