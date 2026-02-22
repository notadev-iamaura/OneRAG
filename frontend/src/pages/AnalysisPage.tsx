import React from 'react';
import { StatsTab } from '../components/StatsTab';
import { ProtectedRoute } from '../components/ProtectedRoute';

export default function AnalysisPage() {

  return (
    <ProtectedRoute title="통계 분석 접근">
      <div className="container mx-auto px-4 py-6 max-w-[1400px]">
        <StatsTab />
      </div>
    </ProtectedRoute>
  );
}
