// Налаштування вьюера. Координати подані в системі glTF (Y вгору): x = схід, y = висота, z = -північ.
// Перерахунок із Blender (X схід, Y північ, Z вгору): gltf = (x, z, -y).
export const CONFIG = {
  modelUrl: 'models/KSU_campus_clean.glb',
  collisionUrl: 'data/collision.bin.gz',   // tools/build_collision.py
  // Для старого GLB із вузлами _SRC_instances: 'models/backup/hidden_nodes_for_old_glb.json'. Для чистого GLB — null.
  hiddenNodesUrl: null,

  maxPixelRatio: 1.5,           // слабка інтегрована графіка: не рендеримо в повну роздільність Retina
  anisotropy: 4,

  sky: 0xa9c9ea,
  fog: { color: 0xbfd6ea, near: 260, far: 760 },

  // Сонце з Blender (KSU_Sun): напрямок "до землі" у Blender = (0.498, 0.638, -0.588) -> glTF (0.498, -0.588, -0.638)
  sun: {
    color: 0xffe8c7,
    intensity: 2.6,
    dir: [0.498, -0.588, -0.638],
    shadowCenter: [40, 0, -20],
    shadowHalfSize: 230,
    shadowMapSize: 4096,
  },
  hemi: { sky: 0xcfe2ff, ground: 0x59614a, intensity: 1.15 },
  exposure: 1.0,

  // Точки огляду (позиція -> ціль), взяті з перевірочних кадрів Blender.
  views: {
    aerial:     { pos: [60, 40, 105],   target: [0, 8, -20] },
    athena:     { pos: [50, 3.5, -42],  target: [40, 1, -66] },
    park:       { pos: [100.5, 2.6, -69.5], target: [88, 0.4, -63.5] },
    parkAerial: { pos: [70, 55, -20],   target: [105, 0, -75] },
    sport:      { pos: [14, 12, -132],  target: [30, 0, -98] },
    // наземні точки (телепорт у режим прогулянки)
    main:       { pos: [84, 0, 22],     target: [25, 12, -5] },
    dorm:       { pos: [40, 0, 45],     target: [82, 8, 52] },
    courts:     { pos: [92, 0, -112],   target: [65, 1.5, -100] },
  },
  startView: 'aerial',

  // Старт: 'walk' — прогулянка від першої особи, 'free' — вільний огляд
  startMode: 'walk',   // у режимі сайту стартова точка береться з spawn
  spawn: { pos: [50, 0, -42], target: [40, 1.6, -66] },
  // Перевизначення параметрів гравця (js/player.js, PLAYER_DEFAULTS): walkSpeed, runSpeed, eyeHeight, jumpSpeed …
  player: {},
};
