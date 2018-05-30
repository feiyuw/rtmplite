VERSION:=1.0

MXMLC45:=/Users/zhangyu/Flex/bin/mxmlc

BINARIES:= bin-debug/testP2P.swf

all: ${BINARIES}

bin-debug/testP2P.swf: src/testP2P.mxml Makefile
	${MXMLC45} -output $@ -compiler.debug=true \
	-swf-version=29 -target-player 29.0 \
	-static-link-runtime-shared-libraries=true -source-path src -- src/testP2P.mxml

clean:
	rm -f bin-debug/testP2P.swf
