import type { Factory, Machine, ProductionLine, Sku, User } from '@/types'

export const factories: Factory[] = [
  {
    id: 'fac-north',
    name: 'Northfield Plant',
    code: 'NFP',
    location: 'Leeds, United Kingdom',
    timezone: 'Europe/London',
  },
  {
    id: 'fac-south',
    name: 'Southgate Plant',
    code: 'SGP',
    location: 'Valencia, Spain',
    timezone: 'Europe/Madrid',
  },
]

export const productionLines: ProductionLine[] = [
  {
    id: 'line-n1',
    factoryId: 'fac-north',
    name: 'Line 1 — Doypack',
    code: 'NFP-L1',
    status: 'running',
    ratedSpeedPpm: 120,
  },
  {
    id: 'line-n2',
    factoryId: 'fac-north',
    name: 'Line 2 — Sachet',
    code: 'NFP-L2',
    status: 'running',
    ratedSpeedPpm: 180,
  },
  {
    id: 'line-s1',
    factoryId: 'fac-south',
    name: 'Line 3 — Stickpack',
    code: 'SGP-L3',
    status: 'changeover',
    ratedSpeedPpm: 150,
  },
]

export const machines: Machine[] = [
  {
    id: 'mac-1',
    lineId: 'line-n1',
    factoryId: 'fac-north',
    name: 'Filler A1',
    code: 'NFP-L1-FA1',
    model: 'HFFS-4200',
    type: 'Horizontal form-fill-seal',
    status: 'running',
    commissionedOn: '2019-04-16',
  },
  {
    id: 'mac-2',
    lineId: 'line-n1',
    factoryId: 'fac-north',
    name: 'Sealer A2',
    code: 'NFP-L1-SA2',
    model: 'SLR-880',
    type: 'Rotary heat sealer',
    status: 'running',
    commissionedOn: '2019-04-16',
  },
  {
    id: 'mac-3',
    lineId: 'line-n2',
    factoryId: 'fac-north',
    name: 'Filler B1',
    code: 'NFP-L2-FB1',
    model: 'VFFS-2600',
    type: 'Vertical form-fill-seal',
    status: 'running',
    commissionedOn: '2021-09-02',
  },
  {
    id: 'mac-4',
    lineId: 'line-n2',
    factoryId: 'fac-north',
    name: 'Checkweigher B2',
    code: 'NFP-L2-CB2',
    model: 'CW-140',
    type: 'Dynamic checkweigher',
    status: 'running',
    commissionedOn: '2021-09-02',
  },
  {
    id: 'mac-5',
    lineId: 'line-s1',
    factoryId: 'fac-south',
    name: 'Stickpack C1',
    code: 'SGP-L3-SC1',
    model: 'STP-3000',
    type: 'Multi-lane stickpack',
    status: 'maintenance',
    commissionedOn: '2022-11-28',
  },
]

export const skus: Sku[] = [
  {
    id: 'sku-1',
    code: 'SKU-4180',
    name: 'Ground Coffee 500 g',
    productType: 'Ground coffee',
    packFormat: 'Doypack 500 g',
    targetWeightG: 500,
  },
  {
    id: 'sku-2',
    code: 'SKU-4192',
    name: 'Ground Coffee 250 g',
    productType: 'Ground coffee',
    packFormat: 'Doypack 250 g',
    targetWeightG: 250,
  },
  {
    id: 'sku-3',
    code: 'SKU-5240',
    name: 'Protein Powder 1 kg',
    productType: 'Nutritional powder',
    packFormat: 'Doypack 1 kg',
    targetWeightG: 1000,
  },
  {
    id: 'sku-4',
    code: 'SKU-6015',
    name: 'Instant Soup Sachet 18 g',
    productType: 'Dehydrated soup',
    packFormat: 'Sachet 18 g',
    targetWeightG: 18,
  },
  {
    id: 'sku-5',
    code: 'SKU-7301',
    name: 'Electrolyte Stick 6 g',
    productType: 'Electrolyte powder',
    packFormat: 'Stickpack 6 g',
    targetWeightG: 6,
  },
]

/** Mock signed-in operator. Phase 1 has no authentication of any kind. */
export const currentUser: User = {
  id: 'usr-1',
  name: 'Marta Ibáñez',
  initials: 'MI',
  role: 'Process Engineer',
  email: 'm.ibanez@example.com',
  shift: 'A',
}

export const mockOperators: readonly string[] = [
  'Marta Ibáñez',
  'Tom Whitfield',
  'Priya Raghavan',
  'Lukas Berger',
  'Sofia Almeida',
]

export const factoryById = new Map(factories.map((f) => [f.id, f]))
export const lineById = new Map(productionLines.map((l) => [l.id, l]))
export const machineById = new Map(machines.map((m) => [m.id, m]))
export const skuById = new Map(skus.map((s) => [s.id, s]))
