import { Routes } from '@angular/router';
import { TopologyComponent } from './pages/topology/topology.component';
import { InferenceComponent } from './pages/inference/inference.component';
import { EvaluationComponent } from './pages/evaluation/evaluation.component';
import { ResultsComponent } from './pages/results/results.component';

export const routes: Routes = [
  { path: '', redirectTo: 'topology', pathMatch: 'full' },
  { path: 'topology',   component: TopologyComponent },
  { path: 'inference',  component: InferenceComponent },
  { path: 'evaluation', component: EvaluationComponent },
  { path: 'results',    component: ResultsComponent },
];
