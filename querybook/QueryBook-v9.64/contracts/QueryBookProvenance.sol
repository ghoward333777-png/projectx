// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// QueryBook Provenance NFTs — Registry 8.8.1–8.8.10.
///
/// A self-contained ERC-721 (no imports) in which each token certifies one QueryBook
/// object (a QBF document, a Fact Unit, a provenance chain or an answer) by its content
/// hash. Metadata lives fully on-chain as a data: URI. Tokens can be re-minted as
/// successors (lineage chain, 8.8.5) and revoked with a reason (8.8.10). Only the
/// deploying QueryBook node (the minter) can mint or revoke; holders transfer normally.
interface IERC721Receiver {
    function onERC721Received(address operator, address from, uint256 tokenId, bytes calldata data)
        external returns (bytes4);
}

contract QueryBookProvenance {
    string public constant name = "QueryBook Provenance";
    string public constant symbol = "QBP";

    address public immutable minter;
    uint256 public totalSupply;

    mapping(uint256 => address) private _owners;
    mapping(address => uint256) private _balances;
    mapping(uint256 => address) private _tokenApprovals;
    mapping(address => mapping(address => bool)) private _operatorApprovals;
    mapping(uint256 => string) private _uris;

    mapping(uint256 => bytes32) public contentHashOf;   // QueryBook object hash (DPH / FUPH / seal)
    mapping(uint256 => uint256) public predecessorOf;   // 0 = first in its lineage
    mapping(uint256 => uint256) public successorOf;     // 0 = current
    mapping(uint256 => bool) public revoked;
    mapping(bytes32 => uint256) public tokenOfContentHash;

    event Transfer(address indexed from, address indexed to, uint256 indexed tokenId);
    event Approval(address indexed owner, address indexed approved, uint256 indexed tokenId);
    event ApprovalForAll(address indexed owner, address indexed operator, bool approved);
    event Minted(uint256 indexed tokenId, bytes32 indexed contentHash, uint256 predecessorId);
    event Revoked(uint256 indexed tokenId, string reason);

    constructor() {
        minter = msg.sender;
    }

    modifier onlyMinter() {
        require(msg.sender == minter, "QBP: only the QueryBook node can do this");
        _;
    }

    // ---- ERC-165 ----
    function supportsInterface(bytes4 id) external pure returns (bool) {
        return id == 0x01ffc9a7 // ERC-165
            || id == 0x80ac58cd // ERC-721
            || id == 0x5b5e139f; // ERC-721 Metadata
    }

    // ---- ERC-721 ----
    function balanceOf(address owner) external view returns (uint256) {
        require(owner != address(0), "QBP: zero address");
        return _balances[owner];
    }

    function ownerOf(uint256 tokenId) public view returns (address) {
        address owner = _owners[tokenId];
        require(owner != address(0), "QBP: no such token");
        return owner;
    }

    function tokenURI(uint256 tokenId) external view returns (string memory) {
        ownerOf(tokenId);
        return _uris[tokenId];
    }

    function approve(address to, uint256 tokenId) external {
        address owner = ownerOf(tokenId);
        require(msg.sender == owner || _operatorApprovals[owner][msg.sender], "QBP: not allowed");
        _tokenApprovals[tokenId] = to;
        emit Approval(owner, to, tokenId);
    }

    function getApproved(uint256 tokenId) external view returns (address) {
        ownerOf(tokenId);
        return _tokenApprovals[tokenId];
    }

    function setApprovalForAll(address operator, bool approved) external {
        _operatorApprovals[msg.sender][operator] = approved;
        emit ApprovalForAll(msg.sender, operator, approved);
    }

    function isApprovedForAll(address owner, address operator) external view returns (bool) {
        return _operatorApprovals[owner][operator];
    }

    function transferFrom(address from, address to, uint256 tokenId) public {
        address owner = ownerOf(tokenId);
        require(owner == from, "QBP: wrong owner");
        require(to != address(0), "QBP: zero address");
        require(msg.sender == owner || _tokenApprovals[tokenId] == msg.sender || _operatorApprovals[owner][msg.sender],
            "QBP: not allowed");
        delete _tokenApprovals[tokenId];
        unchecked {
            _balances[from] -= 1;
            _balances[to] += 1;
        }
        _owners[tokenId] = to;
        emit Transfer(from, to, tokenId);
    }

    function safeTransferFrom(address from, address to, uint256 tokenId) external {
        safeTransferFrom(from, to, tokenId, "");
    }

    function safeTransferFrom(address from, address to, uint256 tokenId, bytes memory data) public {
        transferFrom(from, to, tokenId);
        if (to.code.length > 0) {
            require(IERC721Receiver(to).onERC721Received(msg.sender, from, tokenId, data)
                == IERC721Receiver.onERC721Received.selector, "QBP: receiver refused");
        }
    }

    // ---- QueryBook ----
    /// Mint a certificate for `contentHash`. `predecessorId` > 0 re-mints a successor in an
    /// existing lineage (the predecessor must exist and not already have a successor).
    function mint(address to, string calldata uri, bytes32 contentHash, uint256 predecessorId)
        external onlyMinter returns (uint256 tokenId)
    {
        require(to != address(0), "QBP: zero address");
        require(contentHash != bytes32(0), "QBP: empty hash");
        require(tokenOfContentHash[contentHash] == 0, "QBP: already certified");
        if (predecessorId != 0) {
            ownerOf(predecessorId);
            require(successorOf[predecessorId] == 0, "QBP: predecessor already superseded");
        }
        tokenId = ++totalSupply;
        _owners[tokenId] = to;
        unchecked { _balances[to] += 1; }
        _uris[tokenId] = uri;
        contentHashOf[tokenId] = contentHash;
        tokenOfContentHash[contentHash] = tokenId;
        if (predecessorId != 0) {
            predecessorOf[tokenId] = predecessorId;
            successorOf[predecessorId] = tokenId;
        }
        emit Transfer(address(0), to, tokenId);
        emit Minted(tokenId, contentHash, predecessorId);
    }

    /// Revoke a certificate (it stays on-chain, flagged, with the reason in the event log).
    function revoke(uint256 tokenId, string calldata reason) external onlyMinter {
        ownerOf(tokenId);
        require(!revoked[tokenId], "QBP: already revoked");
        revoked[tokenId] = true;
        emit Revoked(tokenId, reason);
    }
}
