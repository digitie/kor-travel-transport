"use client";

import type { ReactNode } from "react";

import { FeeCalculator } from "../fee-calculator";
import { Alert } from "../ui/alert";
import { useDashboard } from "../../lib/dashboard-context";

export function FeesView({ scopeControls = true, help }: { scopeControls?: boolean; help?: ReactNode }) {
  const { airports, selectedAirportCode, selectedParkingLotId, onAirportChange, onParkingLotChange, api, error, loading } = useDashboard();

  if (airports.length === 0) {
    return (
      <div className="page-shell">
        {/* T-038 Hallmark audit: a screen reader is not guaranteed to announce a live
            region that arrives already-mounted with its final content - keep this
            announcer permanently mounted and let only its content change. */}
        <p className="sr-only" aria-live="polite">
          {loading ? "공항 목록을 불러오는 중입니다." : ""}
        </p>
        {error ? (
          <Alert className="notice error" variant="destructive">
            {error}
          </Alert>
        ) : (
          <p className="notice" aria-hidden="true">
            {loading ? "공항 목록을 불러오는 중입니다." : "저장된 공항이 없습니다."}
          </p>
        )}
      </div>
    );
  }

  return (
    <div className="page-shell">
      <FeeCalculator
        airports={airports}
        initialAirportCode={selectedAirportCode || airports[0].code}
        initialParkingLotId={selectedParkingLotId}
        onAirportChange={onAirportChange}
        onParkingLotChange={onParkingLotChange}
        scopeControls={scopeControls}
        help={help}
        onCalculate={api.calculateFee}
      />
    </div>
  );
}
