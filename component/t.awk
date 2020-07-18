BEGIN {
    c = 0
    switch (c) {
    case 0:
        print 0
        c = 2
        break
    case 1:
        print 1
        break
    case 2:
        print 2
    }
}