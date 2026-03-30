// ============================================================
//  SMART MIRROR FRAME  –  4-piece snap-together  (PORTRAIT)
//
//  Monitor physical size : 19" x 11" x 1"
//    → 482.6 mm tall  (MON_H, vertical / long side)
//    → 279.4 mm wide  (MON_W, horizontal / short side)
//    → 25.4  mm deep  (MON_D)
//
//  Portrait orientation:
//    TOP  & BOTTOM rails  = SHORT  (span the 279.4 mm width)
//    LEFT & RIGHT  rails  = TALL   (span the 482.6 mm height)
//    Corner joints: TALL side rails carry TABS,
//                   SHORT top/bottom rails carry SOCKETS.
//
//  Camera : Logitech 101  (fully embedded in short top rail)
//    stand  : 42.5 x 30 x 10 mm
//    body   : 20  x 20 x 30 mm  (lens faces mirror front / -Y)
//
//  PARTS  →  set PART below, then render / export each STL:
//    "top"    short top rail  (embedded camera, lens port, cable exit)
//    "bottom" short bottom rail
//    "left"   tall left rail
//    "right"  tall right rail  (identical to left, print 2)
//    "all"    exploded view
// ============================================================

PART = "all";   // ← change to "top" / "bottom" / "left" / "right"

// ----------------------------------------------------------
//  MONITOR DIMENSIONS
// ----------------------------------------------------------
MON_W = 279.4;   // short side – width  (X)
MON_H = 482.6;   // long  side – height (Y / portrait axis)
MON_D =  25.4;   // depth (Z)

// ----------------------------------------------------------
//  FRAME PROFILE  (same cross-section on all four rails)
// ----------------------------------------------------------
WALL   = 6;            // outer wall / skin thickness
LIP    = 8;            // rear flange depth that tucks behind monitor
REVEAL = 4;            // front bezel overlap over monitor face
DEPTH  = MON_D + WALL; // full channel depth ≈ 31.4 mm

// ----------------------------------------------------------
//  DOVETAIL SNAP JOINT GEOMETRY
// ----------------------------------------------------------
TAB_W  = 16;           // base width of dovetail
TAB_H  =  8;           // protrusion length
TAB_T  = DEPTH - 2;    // thickness (nearly full depth)
DRAFT  =  2;           // taper on each side
CLEAR  =  0.3;         // fit clearance (tighten to 0.2 for resin)

// ----------------------------------------------------------
//  CAMERA DIMENSIONS  (Logitech 101)
// ----------------------------------------------------------
CAM_SL  = 42.5;   // stand length (X)
CAM_SW  = 30.0;   // stand width  (Y, front-to-back)
CAM_SH  = 10.0;   // stand height (Z)

CAM_BL  = 20.0;   // body length  (X)
CAM_BW  = 20.0;   // body width   (Y)
CAM_BH  = 30.0;   // body height  (Z)

CAM_CLR =  0.4;   // cavity clearance on all faces
LENS_D  = 10.0;   // lens port diameter
CABLE_W =  8.0;   // USB cable channel width

// Top rail Z-height must accommodate camera stack + wall skins
CAM_STACK  = CAM_SH + CAM_BH;          // 40 mm
TOP_RAIL_H = CAM_STACK + 2*WALL;       // 52 mm

// Normal short-rail height (bottom rail uses this)
SHORT_H    = WALL + LIP + REVEAL;      // 18 mm

// ============================================================
//  dovetail_tab()
//  Positive shape. Protrusion points in +X at call site;
//  caller rotates as needed.
// ============================================================
module dovetail_tab() {
    linear_extrude(TAB_T, center=true)
    polygon([
        [ 0,       -(TAB_W/2)        ],
        [ 0,        (TAB_W/2)        ],
        [ TAB_H,    (TAB_W/2 - DRAFT)],
        [ TAB_H,   -(TAB_W/2 - DRAFT)]
    ]);
}

// ============================================================
//  dovetail_socket()
//  Negative shape (subtract). Same profile + CLEAR.
// ============================================================
module dovetail_socket() {
    c = CLEAR;
    linear_extrude(TAB_T + 2*c, center=true)
    polygon([
        [-0.5,      -(TAB_W/2 + c)        ],
        [-0.5,       (TAB_W/2 + c)        ],
        [ TAB_H+0.5, (TAB_W/2 - DRAFT + c)],
        [ TAB_H+0.5,-(TAB_W/2 - DRAFT + c)]
    ]);
}

// ============================================================
//  TOP RAIL  (short, camera embedded)
//
//  Axes in this module:
//    X  = rail length  (0 … MON_W + 2*WALL)
//    Y  = front-to-back (0 = mirror front face)
//    Z  = rail height   (0 = inner bottom edge, TOP_RAIL_H = top)
//
//  - Monitor slot opens on bottom face (Z≈0), full X width
//  - Dovetail SOCKETS at each X end  (tab from side rail slides in)
//  - Camera stand cavity at Z=WALL (just above inner bottom skin)
//  - Camera body cavity stacked above stand cavity
//  - Lens port Ø LENS_D punched through front face (Y=0)
//  - Cable channel exits rear face (Y=DEPTH)
//  - Top-face access slot so camera can be dropped in during build
// ============================================================
module top_rail() {
    L = MON_W + 2*WALL;   // 291.4 mm

    // Camera X centre (centred in rail)
    cx = L / 2;

    // Stand cavity
    sx0 = cx - (CAM_SL + 2*CAM_CLR) / 2;
    sy0 = (DEPTH - (CAM_SW + 2*CAM_CLR)) / 2;
    sz0 = WALL;

    // Body cavity (centred on stand in X and Y, sits on top of stand)
    bx0 = cx - (CAM_BL + 2*CAM_CLR) / 2;
    by0 = (DEPTH - (CAM_BW + 2*CAM_CLR)) / 2;
    bz0 = sz0 + CAM_SH + 2*CAM_CLR;

    // Lens port Z centre (mid-height of body cavity)
    lens_z = bz0 + (CAM_BH + 2*CAM_CLR) / 2;

    difference() {
        // ---- solid rail block ----
        cube([L, DEPTH, TOP_RAIL_H]);

        // ---- monitor slot – bottom face ----
        translate([WALL, REVEAL, -0.1])
        cube([MON_W, LIP + WALL + 0.1, WALL + 0.2]);

        // ---- dovetail socket – left end (X=0, opens in -X) ----
        translate([0, DEPTH/2, TOP_RAIL_H/2])
        rotate([0, 90, 0])   // protrusion now points in -X (into socket opening)
        rotate([0,  0, 90])
        dovetail_socket();

        // ---- dovetail socket – right end (X=L, opens in +X) ----
        translate([L, DEPTH/2, TOP_RAIL_H/2])
        rotate([0, -90, 0])
        rotate([0,   0, 90])
        dovetail_socket();

        // ---- stand cavity ----
        translate([sx0, sy0, sz0])
        cube([CAM_SL + 2*CAM_CLR,
              CAM_SW + 2*CAM_CLR,
              CAM_SH + 2*CAM_CLR]);

        // ---- body cavity ----
        translate([bx0, by0, bz0])
        cube([CAM_BL + 2*CAM_CLR,
              CAM_BW + 2*CAM_CLR,
              CAM_BH + 2*CAM_CLR]);

        // ---- lens port (through front face Y=0) ----
        translate([cx, -0.1, lens_z])
        rotate([-90, 0, 0])
        cylinder(h = WALL + 1, r = LENS_D/2, $fn = 64);

        // ---- cable channel (exits rear face Y=DEPTH) ----
        translate([(L - CABLE_W)/2, DEPTH - WALL - 0.1, bz0])
        cube([CABLE_W, WALL + 0.2, CABLE_W]);

        // ---- top access slot for drop-in camera assembly ----
        translate([bx0, by0, TOP_RAIL_H - 0.1])
        cube([CAM_BL + 2*CAM_CLR,
              CAM_BW + 2*CAM_CLR,
              WALL + 0.2]);
    }
}

// ============================================================
//  BOTTOM RAIL  (short, no camera)
//
//  Same X/Y layout as top rail; shorter Z (SHORT_H = 18 mm).
//  Monitor slot opens on TOP face (Z = SHORT_H).
// ============================================================
module bottom_rail() {
    L = MON_W + 2*WALL;

    difference() {
        cube([L, DEPTH, SHORT_H]);

        // ---- monitor slot – top face ----
        translate([WALL, REVEAL, SHORT_H - WALL - 0.1])
        cube([MON_W, LIP + WALL + 0.1, WALL + 0.2]);

        // ---- dovetail socket – left end ----
        translate([0, DEPTH/2, SHORT_H/2])
        rotate([0, 90, 0])
        rotate([0,  0, 90])
        dovetail_socket();

        // ---- dovetail socket – right end ----
        translate([L, DEPTH/2, SHORT_H/2])
        rotate([0, -90, 0])
        rotate([0,   0, 90])
        dovetail_socket();
    }
}

// ============================================================
//  SIDE RAIL  (tall – left or right, print 2)
//
//  Axes:
//    X  = rail cross-section width  (WALL + LIP + REVEAL)
//    Y  = front-to-back (0 = front face)
//    Z  = height  (0 … MON_H = 482.6 mm)
//
//  - Monitor slot opens on interior face (X = WALL+LIP+REVEAL)
//  - Dovetail TABS at Z=0 (bottom, pointing down) and
//    Z=MON_H (top, pointing up)
//    → tabs slide into the sockets of the short rails
// ============================================================
module side_rail() {
    RW = WALL + LIP + REVEAL;   // cross-section width ≈ 18 mm

    difference() {
        union() {
            // ---- rail body ----
            cube([RW, DEPTH, MON_H]);

            // ---- dovetail tab – bottom end (points in -Z) ----
            translate([RW/2, DEPTH/2, 0])
            rotate([0, 180, 0])   // flip so protrusion goes -Z
            rotate([90, 0, 0])
            dovetail_tab();

            // ---- dovetail tab – top end (points in +Z) ----
            translate([RW/2, DEPTH/2, MON_H])
            rotate([90, 0, 0])
            dovetail_tab();
        }

        // ---- monitor slot (interior face) ----
        translate([REVEAL, REVEAL, -0.1])
        cube([LIP + WALL + 0.1, DEPTH - REVEAL, MON_H + 0.2]);
    }
}

// ============================================================
//  EXPLODED VIEW
// ============================================================
module all_parts() {
    g  = 50;   // gap between parts
    RW = WALL + LIP + REVEAL;

    // top rail – above
    translate([0, 0, MON_H + g])
    top_rail();

    // bottom rail – below
    translate([0, 0, -(SHORT_H + g)])
    bottom_rail();

    // left side rail
    translate([-(RW + g), 0, 0])
    side_rail();

    // right side rail
    translate([MON_W + 2*WALL + g, 0, 0])
    side_rail();
}

// ============================================================
//  RENDER
// ============================================================
if      (PART == "top")    top_rail();
else if (PART == "bottom") bottom_rail();
else if (PART == "left")   side_rail();
else if (PART == "right")  side_rail();
else                       all_parts();
