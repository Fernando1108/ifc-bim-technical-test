import { useRef, useEffect } from "react"
import Chart from "chart.js/auto"
import type { IfcAnalyticsTypeCount } from "../api/models"

interface IfcTypeChartProps {
  data: IfcAnalyticsTypeCount[]
}

const MAX_TYPES = 15

export default function IfcTypeChart({ data }: IfcTypeChartProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const chartRef = useRef<Chart | null>(null)

  useEffect(() => {
    if (!canvasRef.current) return

    const sliced = data.slice(0, MAX_TYPES)

    chartRef.current?.destroy()

    chartRef.current = new Chart(canvasRef.current, {
      type: "bar",
      data: {
        labels: sliced.map((d) => d.ifc_type),
        datasets: [
          {
            label: "Elementos",
            data: sliced.map((d) => d.count),
            backgroundColor: "rgba(37, 99, 235, 0.75)",
            borderColor: "rgba(37, 99, 235, 1)",
            borderWidth: 1,
          },
        ],
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 300 },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (ctx) => `${ctx.dataset.label}: ${(ctx.parsed.x ?? 0).toLocaleString()}`,
            },
          },
        },
        scales: {
          x: {
            beginAtZero: true,
            ticks: { precision: 0 },
          },
          y: {
            ticks: { font: { size: 11 } },
          },
        },
      },
    })

    return () => {
      chartRef.current?.destroy()
      chartRef.current = null
    }
  }, [data])

  return (
    <canvas
      ref={canvasRef}
      aria-label="Gráfico de barras horizontales mostrando cantidad de elementos por clase IFC"
      role="img"
    />
  )
}
